# P2: Training pipeline (retrain → gate → serve)

Part of [PLAN.md](../PLAN.md) §5. **Status (2026-11-13): done.** Results and findings at the end. **Cost: $0.** Everything runs in the same kind cluster as P1.

**Goal:** the *training* half of the platform. A raw data export goes in; a validated, versioned model comes out and reaches the classifier pod, with every step automated and every bad run stopped before production.

![Training pipeline](../diagrams/training-pipeline.svg)

**What changes for P1:** today the classifier's `model.joblib` is copied by hand from the B2 folder and baked into the image. After P2 it is **produced by the pipeline and pulled at startup**, so the image holds only serving code, and a new model ships by changing one Helm value.

---

## What we build

| Piece | What it is | Runs as |
| --- | --- | --- |
| **SeaweedFS** | An open-source, S3-compatible store: our laptop stand-in for S3. (The plan said MinIO, but MinIO no longer publishes free container images; see findings.) Two buckets: **`mlops`** for the pipeline (`raw/` exports, `datasets/<version>/`, `mlflow/` files, `argo/` step files) and **`models`** for published models, the only bucket serving can read | Deployment + volume, namespace `mlops` |
| **PostgreSQL** | MLflow's database: runs, metrics, model versions, aliases. A real SQL database instead of SQLite, as in production (RDS on EKS) | Deployment + volume, namespace `mlops` |
| **MLflow server** | Tracking (every run's settings and scores) and the **registry** (model versions with the aliases `challenger` and `champion`). Database: PostgreSQL; files in SeaweedFS | Deployment, namespace `mlops` |
| **Argo Workflows** | Runs pipelines on Kubernetes, one pod per step, steps in order; a failed step stops the run | Helm chart, namespace `argo` |
| **Trainer image** (`trainer:dev`) | The B2 code (`validate.py`, `train.py`, MLflow tracking, `registry.py`) plus new `prepare.py`, a PyTorch candidate (`torch_model.py`) and `publish.py`. Pinned scikit-learn 1.6.1 and CPU-only PyTorch, the same versions as the serving image | Used by every pipeline step |
| **WorkflowTemplate** `train-classifier` | The pipeline definition: `prepare → validate → train → compare → publish`. Inputs: the raw file and the model name, so another team could reuse it | A Kubernetes object; `make train RAW=<file>` creates a `Workflow` from it (no argo CLI needed) |
| **Classifier, changed** | An **init container** downloads `models/dispute-classifier/v<N>/` before the server starts; the server verifies the checksum as before. The image no longer contains the model | The P1 chart, plus `initContainers`; the version is `MODEL_VERSION` in `deploy/local/classifier.yaml` |

---

## New words

| Word | Meaning, with our example |
| --- | --- |
| **Data preparation (ETL)** | *Extract, transform, load*: turning a raw export into training-ready data. Ours: read the CSV, trim whitespace, drop duplicates and unreadable rows, split into train/val/test by label, write parquet + a manifest whose version is a hash of the content |
| **PyTorch** | The most used deep-learning framework (with TensorFlow). Our PyTorch candidate is tiny: word pieces → an averaged embedding → a linear layer (an `EmbeddingBag` classifier). It trains on CPU in a few minutes |
| **Model family / framework** | scikit-learn and PyTorch models are saved and loaded differently. `metadata.json` records the `framework`, so serving knows how to load it; in P5, KServe picks a serving runtime from this "model format" |
| **Kubernetes Job** | A pod that runs to completion and exits (vs a Deployment, which runs forever). Training is a Job; serving is a Deployment |
| **Argo Workflows** | A Kubernetes add-on that chains Job-like steps into a pipeline (a DAG, *directed acyclic graph*: steps with "runs after" arrows and no loops). Kubeflow Pipelines and Airflow do the same job; Argo is the most Kubernetes-native and pairs with Argo CD |
| **WorkflowTemplate** | A reusable pipeline definition stored in the cluster. Each run is a `Workflow` created from it, with its own parameters (here: the raw file) |
| **Conditional step** (`when`) | A step that runs only if an expression is true. Our `publish` runs only when `compare` says the model was promoted |
| **Retry strategy** | Which failures Argo retries. Ours: system errors and killed processes (exit 137), never a failed gate (exit 1) |
| **Artifact (Argo)** | A file or folder one step hands to the next, stored in SeaweedFS/S3 in between, because each step is a different pod with its own disk. Our `train` step outputs the model package; `publish` receives it |
| **Artifact store** | Where files live (SeaweedFS now, S3 on EKS). Different from the registry: the store holds bytes; the registry holds *which version is which* |
| **Model registry** | A catalogue of model versions with their scores, data version and commit. MLflow's registry, already used in B2 |
| **Champion / challenger** | Aliases in the registry. *Challenger* = newest version that passed the gate. *Champion* = the version production should serve. Promotion moves the `champion` alias only if the challenger is at least as good |
| **Init container** | A container that runs to completion **before** the main container starts, in the same pod. Ours downloads the model into a shared `emptyDir` volume |
| **Retraining trigger** | What starts a run. Now: a person runs `make train`. On EKS: a new dataset landing in S3 (Argo Events) or a schedule (`CronWorkflow`) |
| **Data drift** | The real-world inputs change over time (new merchants, new wording), so a model trained on old data gets worse. The reason retraining pipelines exist |

---

## One run, step by step

Input: `raw=claims-2026-11.csv` (the B2 November data exported as one raw CSV, with some duplicates and messy rows added, the way real exports arrive).

| Step | Pod runs | Reads | Writes | Stops the run when |
| --- | --- | --- | --- | --- |
| **0 prepare** | `prepare.py` | the raw CSV from `raw/` | `datasets/<version>/` (train/val/test parquet + manifest); counts of rows dropped and why | the file can't be parsed, required columns are missing, or more than 5% of rows are unusable |
| **1 validate** | `validate.py` | the prepared dataset | nothing | schema wrong, too few rows, a label missing, a class under 8%, text shared between splits (leakage), file hash ≠ manifest |
| **2 train** | `train.py` | the dataset | trains the **scikit-learn** settings and the **PyTorch** candidate, picks the best on validation; model package (Argo artifact); MLflow run with every candidate; registers a **challenger** if the gate passes | the gate fails: macro-F1 < 0.90, a language < 0.85, any label's recall < 0.80 |
| **3 compare** | `compare.py` (uses `registry.py promote`) | MLflow: challenger and champion | moves `champion` to the challenger; output `promoted` = true/false | the challenger is worse than the champion on any compared score. If they were trained on different data, both are re-scored on the shared **golden** set. *Same data and same code as the champion* = the same model: not promoted, run still succeeds, publish skipped |
| **4 publish** (only if promoted) | `publish.py` | the model package (Argo artifact) | `models` bucket: `dispute-classifier/v<N>/model.joblib` + `metadata.json` (with `file_sha256` and a `registry` section) | not the champion, checksum mismatch, or v<N> already exists (published versions are never overwritten) |

Then, outside the pipeline (as it would be in production): set `MODEL_VERSION: v<N>` in `deploy/local/classifier.yaml` → `make deploy` → the init container pulls v<N> → the server verifies the checksum → ready. In P7 a bot opens this change as a PR, and Argo CD applies it.

---

## Design choices worth defending

| Choice | Why |
| --- | --- |
| **Each step is its own pod; files pass through the artifact store** | A step can be retried alone (a spot node dies during training: retry `train`, don't redo `validate`). The store keeps every step's output for later debugging |
| **Prepare is a pipeline step, not a script on someone's laptop** | Every dataset version is produced by the same code from a raw file that is kept, so any model can be traced back to the raw export it came from |
| **Two frameworks compete in the same pipeline** | Research teams use different frameworks. The platform's job is the same either way: run it, score it on the same data, gate it, version it. Honest expectation: the TF-IDF model probably wins on this small, template-like data, and that is a fine result. The point is that the decision is measured, not assumed |
| **If PyTorch wins, serving must load PyTorch** | The serving image gains CPU-only PyTorch (about 200 MB more). That's a real platform trade-off: one image per framework, or one larger image. We record `framework` in `metadata.json`, and the server refuses a framework it doesn't support (fail closed) |
| **MLflow on PostgreSQL, not SQLite** | SQLite allows one writer at a time and lives inside one pod. PostgreSQL is what production uses (RDS on EKS), handles concurrent runs from many teams, and can be backed up |
| **Validation and the gate are separate steps** | Validation catches *broken* data (wrong schema, leakage). The gate catches data that is *valid but bad*: our noisy dataset passes every validation check but produces a model with macro-F1 0.73. You need both |
| **Promotion compares against the champion, not only fixed thresholds** | A model can pass "≥ 0.90" while being worse than the 0.98 already in production. Never ship a regression just because it clears the bar |
| **The serving image holds no model** | One image serves any model version: a model change becomes a config change (Helm value), reviewed and rolled back like any other. Images stay small, and rebuilding is not needed for a retrain |
| **The checksum is still verified at load** | The download could be corrupted or tampered with. The pod refuses a file that doesn't match its `metadata.json` (pickles can run code) |
| **Training and serving pin the same library versions** | A model pickled with scikit-learn 1.6.1 must be loaded with 1.6.1 |
| **Code commit is baked into the trainer image** (build argument) | The container has no `.git` folder. The image tag and the recorded commit tie every model to the exact code that produced it |
| **Two S3 identities, scoped per bucket** | `training/scripts/secrets.sh` generates random keys, never printed or committed. The trainer can read/write both buckets; the classifier can **only read `models`**. Verified: its key can't write a model or even list the pipeline bucket. On EKS there are no keys at all: pods get IAM roles via Pod Identity |
| **Same data + same code = nothing to publish** | Re-running a pipeline (a retry, a duplicate trigger) must not create "new" versions that are identical to production. Compare detects it and Argo skips publish |
| **Retries only for interruptions** | A spot interruption or OOM kill (exit 137) or a lost pod is worth retrying. A failed gate is a verdict, not an accident; retrying it wastes compute and gives the same answer |

---

## Files

```
training/
├── Dockerfile                 trainer image: python 3.11-slim, CPU-only PyTorch, pinned libs, uid 10001, GIT_COMMIT build arg
├── requirements.txt           pandas, pyarrow, pandera, scikit-learn 1.6.1, joblib, mlflow 3.1.4, boto3, pytest
├── src/
│   ├── generate_claims.py     from B2 (LABELS, split and content_hash are reused)
│   ├── store.py               NEW: S3 access (SeaweedFS locally, S3 on EKS: only the endpoint changes)
│   ├── prepare.py             NEW: step 0, raw CSV → cleaned, split, versioned dataset
│   ├── validate.py            from B2: step 1; takes a dataset version from the store
│   ├── torch_model.py         NEW: the PyTorch candidate (fit / predict_proba like scikit-learn)
│   ├── train.py               from B2: step 2; PyTorch joins the candidates; commit from GIT_COMMIT
│   ├── tracking.py            from B2: MLflow logging + registration (both frameworks)
│   ├── registry.py            from B2: champion/challenger; datasets from the store
│   ├── compare.py             NEW: step 3, promote / nothing new / worse
│   └── publish.py             NEW: step 4, package → models bucket
├── tools/make_raw_drops.py    plays the data team: B2 datasets → raw CSV exports with duplicates and messy rows
├── mlflow/Dockerfile          MLflow server image (PostgreSQL driver, S3 client)
├── mlops.yaml                 SeaweedFS + PostgreSQL + MLflow (Deployments, Services, volumes)
├── argo-values.yaml           Argo Workflows Helm values (artifact repository = SeaweedFS)
├── workflow.yaml              WorkflowTemplate train-classifier
├── scripts/                   secrets, buckets, upload_raw, train (submit + follow), run_summary, reset
├── raw/                       NOT committed: the raw CSV drops
└── tests/                     prepare (cleaning, versioning, validation) and the PyTorch model
models/classifier/             no model in the image; fetch_model.py (init container); refuses unsupported frameworks;
                               the B2 model moved to tests/fixtures/
deploy/charts/service/         + initContainers
deploy/local/classifier.yaml   + init container that downloads MODEL_VERSION from the models bucket
Makefile                       + mlops, mlops-images, raw-drops, train, runs, ui, mlops-reset
```

---

## Steps

All local; nothing costs money. Installing Argo Workflows downloads its Helm chart and images.

1. **Storage + registry:** deploy SeaweedFS, PostgreSQL and MLflow into `mlops`; create the buckets.
2. **Raw drops:** `make raw-drops` turns the four B2 datasets (`claims` Nov, `claims-dec`, `claims-noisy`, `golden`) into raw CSV exports with some duplicates and messy rows, and uploads them to `raw/`. This plays the data team.
3. **Trainer image:** copy the B2 code, make the small changes, add `prepare.py` and the PyTorch candidate, build `trainer:dev`, load into kind.
4. **Argo Workflows:** install with Helm; point its artifact repository at SeaweedFS.
5. **The pipeline:** apply `workflow.yaml`; run it on the November raw drop. Expect both families in MLflow, v1 to become champion, and v1 to be published.
6. **Serving from the store:** change the classifier to pull the champion with an init container; remove the baked-in model from the image; `make deploy`; `make smoke` still works, and `/v1/classify` reports the registry version and dataset.
7. **Drills** (below).
8. **Write up** results in this file, as in P1.

## Drills

| # | Run on | Expected result | What it proves |
| --- | --- | --- | --- |
| 1 | November raw drop | All 5 steps pass; prepare reports the duplicates it dropped; scikit-learn and PyTorch both in MLflow; v1 champion; served after the values bump | The happy path, end to end |
| 2 | A broken raw drop (one dispute type almost missing) | prepare succeeds, **validate stops it** (class below 8%); nothing trained, MLflow untouched | Bad data never reaches training |
| 2b | A corrupt raw drop (a required column missing) | Stops at **prepare** | Unreadable input fails at the first step |
| 3 | Noisy raw drop (30% wrong labels) | Validation **passes**, training runs, **gate fails** (B2 saw macro-F1 0.70); not registered; production keeps v1 | Valid-but-bad data is caught by the gate, not by validation |
| 4 | December raw drop (9,000 claims) | Gate passes (B2: 0.974). Different test set from v1, so compare re-scores both on `golden`; promoted only if not worse | Real retraining on new data, compared fairly |
| 5 | Kill the training process mid-run (SIGKILL) | Argo retries the step | Retries for spot interruptions (the EKS case) |
| 6 | December raw drop again (same data, same code) | Trained and registered, but compare says "nothing new"; publish skipped; run succeeds | Re-runs don't create fake new versions |

---

## Done when

- [x] `make mlops` brings up SeaweedFS, PostgreSQL, MLflow and Argo, and the UIs open through port-forward.
- [x] One `make train RAW=claims-2026-11.csv` produces a prepared dataset and a registered **and** published v1.
- [x] Drills 5 and 6: a killed training process is retried; an identical re-run publishes nothing.
- [x] MLflow shows the scikit-learn and PyTorch candidates side by side, with the reason one was chosen.
- [x] The classifier image contains no model; the pod pulls the champion (v2) and serves it; `make smoke` passes.
- [x] Drills 2, 2b, 3 and 4 stop (or promote) exactly as expected, each visible in the Argo UI and in MLflow.
- [x] `make test` passes, including the new tests.

## Interview story

> "Training runs as an Argo Workflow on Kubernetes, one pod per step. A raw export is prepared into a versioned dataset, and validation fails fast on schema, leakage or missing classes. scikit-learn and PyTorch candidates are trained and scored on the same data. Then an absolute quality gate, and a comparison against the production model, all before anything is registered. I showed why both layers matter: a dataset with 30% wrong labels passed every validation check but the gate stopped it at macro-F1 0.73. A promoted model is published with a checksum, and the serving image holds no model, so a new version ships as a reviewed config change and rolls back the same way."

---

## Laptop → EKS (P4, P5, P7)

| Here (kind) | On EKS |
| --- | --- |
| SeaweedFS | S3 buckets (Terraform, P4) |
| SeaweedFS password in a Secret | **Pod Identity**: the training service account's IAM role can read `datasets/` and write `models/`; the classifier's role can only read `models/` |
| PostgreSQL in a pod | **RDS PostgreSQL**, private subnets, encrypted (P4) |
| MLflow files in SeaweedFS | MLflow files in S3 |
| One namespace `mlops` | A namespace per team with quotas; serving has priority over training (P5); team isolation (P11) |
| Training pods on the kind node | Training pods on **spot** nodes that Karpenter adds for the run and removes after (scale to zero) |
| `make train` by hand | **Argo Events**: a new file in `raw/` starts the run (P7); the **drift alert** can start it too (P8); a `CronWorkflow` as a weekly safety net |
| Values bump by hand | CI opens the PR; Argo CD deploys; canary in P10 |
| (no GPU) | Optional: LoRA fine-tune of Qwen as a GPU step, checkpoints to S3 so a spot interruption resumes |

---

## What happened (real results, 2026-11-13)

**Commands:** `make mlops` (one-time setup), `make raw-drops`, then `make train RAW=<file>` per drill. Explore with `make ui`: Argo on http://localhost:2746, MLflow on http://localhost:5000.

| # | Raw drop | prepare | validate | train + gate | compare | publish | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `claims-2026-11.csv` (5,892 rows) | ✓ 58 unusable + 115 duplicates dropped → 5,719 | ✓ | ✓ scikit-learn 0.979 (val) beat PyTorch 0.970; test macro-F1 **0.987** | ✓ first champion | ✓ | **v1** published |
| 2 | `claims-broken.csv` | ✓ | ✗ `not_received` is 1% of each split (< 8%) | not run | not run | not run | stopped; nothing trained |
| 2b | `claims-corrupt.csv` | ✗ label column missing | not run | | | | stopped at the first step |
| 3 | `claims-noisy.csv` (30% wrong labels) | ✓ | ✓ **passes** | ✗ gate: macro-F1 **0.729**, every label's recall < 0.80 | not run | not run | logged in MLflow, **not registered** |
| 4 | `claims-2026-12.csv` (8,761 rows) | ✓ | ✓ | ✓ test macro-F1 0.980 | ✓ re-scored v1 and v2 on golden (2,763 claims; 132 removed because a model trained on them): **tie**, 0.9781 each → promoted | ✓ | **v2** published, champion |
| 5+6 | `claims-2026-12.csv` again, training killed mid-run | ✓ | ✓ | attempt 1 killed (exit 137) → **retried**, attempt 2 ✓ | "nothing new": same dataset and code as v2 | **skipped** (`when` false) | run Succeeded, v3 registered but not promoted |

**Serving:** `MODEL_VERSION: v2` → the init container logged `fetched dispute-classifier v2 from s3://models/dispute-classifier/v2/`; `/v1/classify` reports `version 2, dataset 6e375f7616ed, commit bbf40b4-dirty`; the image contains only `server.py`, `fetch_model.py` and `requirements.txt`. `make smoke` gave the right dispute type for all three claims.

**Tests:** 16 pass (assistant 5, classifier 5 incl. the new unsupported-framework test, training 6).

### Findings (good interview material)

1. **MinIO's free images are gone.** Both `quay.io/minio/minio` and Docker Hub refused to serve them. Swapped in SeaweedFS (same S3 API, so no code changed). Lesson: **pin and mirror every third-party image into your own registry** (ECR on EKS); an upstream can disappear overnight.
2. **A startup race broke the registry.** MLflow started before PostgreSQL was ready, and its registry kept answering HTTP 500 even after the database came up. Fix: an init container that waits for `pg_isready`. The general lesson: a dependency being "up later" isn't enough if the client only connects once at start.
3. **The read-only root filesystem exposed a hidden write.** Registering a model failed with `Read-only file system: './mlruns'`: the MLflow server's internal client fell back to a local folder. Without the hardening, it would have silently written into the container. Fix: `MLFLOW_TRACKING_URI` points at PostgreSQL too, and the working directory is the writable `/tmp` volume. **Hardening finds bugs**, not just attacks.
4. **A wrong Helm value failed before any pod existed.** The training step ended in `Error` with no pod and no logs: the artifact `keyFormat` was double-templated. Where to look: the workflow node's *message*, and the rendered ConfigMap, not pod logs.
5. **A test caught a versioning bug.** The same export with rows in a different order produced a different dataset version (the split depended on row order). Fix: sort by claim ID before deduplicating and splitting. Same rows → same version, always.
6. **Deleting a pod is not an interruption drill.** `kubectl delete pod` (even `--force`) didn't trigger a retry: training finished inside the grace period, and Argo v4 still got the result from its executor. A real interruption kills the process: `kill -9` did (exit 137), and the retry rule took over.
7. **Re-runs created fake new versions.** Before the fix, three re-runs on the December data registered v3–v5, identical to v2, each "promoted" on a tie and published. Added the "nothing new" check and a conditional publish (drill 6).
8. **The evaluation set can't tell good models apart.** v1 and v2 tied to four decimals on golden, because both only miss the 2% deliberately wrong labels. A tie promotes the newer data, which is reasonable, but a real comparison set needs harder cases: the P3 golden set should include real-style wording, typos and edge cases.
9. **PyTorch lost every time** (0.970 vs 0.979 on validation): as expected on short, template-like text. The pipeline recorded both and chose by measurement, which is the point.
10. **Real-wording confidence is still low** (0.49–0.75 in `make smoke`): retraining on more template data doesn't fix it. That's a data problem for the data team, and exactly what drift monitoring (P8) and a better golden set (P3) should surface.
