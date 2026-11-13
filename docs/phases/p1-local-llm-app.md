# P1: The LLM app on your laptop

Part of [PLAN.md](../PLAN.md) §5. **Status (2026-11-13): done.** **Cost: $0.** Everything runs in a local Kubernetes cluster (kind) on your Mac.

**Goal:** the whole request path working on Kubernetes:

```
claim → Assistant API → classifier (dispute type) → policy text → LLM (draft reply) → response
```

---

## What we build

| Piece | What it is | Image | Port |
| --- | --- | --- | --- |
| **llm** | **llama.cpp server** running **Qwen2.5-0.5B-Instruct**, 4-bit (GGUF, 491 MB). OpenAI-compatible API (`/v1/chat/completions`) | `ghcr.io/ggml-org/llama.cpp:server` (official) | 8080 |
| **classifier** | The B2 scikit-learn model behind a small FastAPI app: `POST /v1/classify` | built here: `classifier:dev` | 8000 |
| **assistant** | The app: `POST /assist`. It calls the classifier, picks the policy, fills the prompt, calls the LLM | built here: `assistant:dev` | 8000 |

All three are deployed with **one shared Helm chart** (`deploy/charts/service`) and a values file each (`deploy/local/*.yaml`). That's how platform teams usually work: one standard, reviewed chart that every service reuses, instead of a hand-written chart per service.

**Why llama.cpp and not Ollama (a change from the plan):** Plan B runs llama.cpp on EKS, so running the same image on the laptop means what we test locally is what runs in the cloud. Ollama is built on llama.cpp anyway.

---

## New words

| Word | Meaning, with our example |
| --- | --- |
| **GGUF** | A single-file format for LLM weights used by llama.cpp. Ours: `qwen2.5-0.5b-instruct-q4_k_m.gguf` |
| **Quantization (Q4_K_M)** | Storing each weight in about 4 bits instead of 16. The file shrinks about 4× (1 GB → 491 MB) and runs faster on CPU, at a small cost in quality |
| **OpenAI-compatible API** | The same request format as OpenAI's `/v1/chat/completions`. Our app code doesn't care whether llama.cpp, vLLM, Bedrock (through the gateway) or OpenAI answers. Only the URL changes |
| **System prompt** | Standing instructions for the model ("You draft replies for Maple Bank's dispute team… never promise a refund") |
| **Prompt template** | The message with blanks, filled per request: `Customer claim: {claim} … Policy: {policy}` |
| **Temperature** | Randomness. 0 = always pick the most likely next word; we use 0.2 so replies stay consistent |
| **Prompt version** | Prompts live in files (`app/prompts/draft_reply/v1.yaml`). Every response says which version produced it, so a bad answer can be traced to its prompt. P3 puts prompt changes behind the evaluation gate |
| **Liveness probe** | Kubernetes asks "is the process alive?" (`/healthz`). If not, it restarts the container |
| **Readiness probe** | "Can you take traffic now?" (`/readyz`). Until yes, Kubernetes sends no requests to this pod. The LLM pod is "not ready" while it loads the model |
| **hostPath / extraMounts** | The 491 MB model is downloaded **once** to `local/models/` on your Mac and mounted into the cluster, so a pod restart doesn't download it again. This is the laptop version of the "model cache" in the architecture diagram; on EKS (P5) the weights come from S3 |
| **kind** | "Kubernetes in Docker": a real Kubernetes cluster running as a Docker container on your Mac |
| **`kind load`** | Copies a locally built image into the kind cluster, so no registry is needed |

---

## How a request flows

1. `curl localhost:8080/assist -d '{"text": "I was charged twice at BestElectro for $49.99"}'`
2. kind maps your Mac's port 8080 to the assistant's NodePort (30080).
3. The assistant calls `classifier:8000/v1/classify` → `duplicate_charge`, confidence 0.97.
4. It looks up the policy for `duplicate_charge` in `app/policies.yaml`.
5. It fills the prompt template `draft_reply/v1` and calls `llm:8080/v1/chat/completions`.
6. It returns:
   - the dispute type and confidence;
   - the draft reply;
   - the prompt version and model name;
   - token counts and timings.

**Metrics** (`/metrics`, read by Prometheus in P8):
- requests and errors;
- latency, for the whole request and for the LLM call alone;
- tokens in and out;
- how often each dispute type comes up.

---

## Design choices worth defending

| Choice | Why |
| --- | --- |
| **The classifier verifies the model's checksum before loading it** (`file_sha256` from `metadata.json`) | joblib/pickle files can run code when loaded. A model that doesn't match its recorded fingerprint is refused, and the pod never becomes ready |
| **The classifier pins scikit-learn 1.6.1, numpy 2.4.6, scipy 1.17.1** | The exact versions the model was saved with (from B2's `metadata.json`). A pickled model loaded with other versions can break or silently behave differently |
| **The assistant's `/readyz` checks only itself** (prompts and policies loaded), not the classifier or LLM | If readiness depended on the LLM, one slow LLM would make *every* assistant pod "not ready", and Kubernetes would pull them all out of service: a cascading outage. Dependency health is reported separately at `/status` and through metrics |
| **Containers run as non-root, read-only root filesystem, no privilege escalation** | Least privilege from day one; P11 enforces it cluster-wide |
| **Requests and limits on every pod** | The scheduler needs requests to place pods. Limits stop one pod (usually the LLM) from starving the others |
| **The LLM call has a timeout** (30 s) | A stuck model must not hold the request forever. P6 adds fallback to Bedrock when it times out |

---

## Commands

```bash
make model      # download the GGUF once into local/models/ (491 MB)
make cluster    # create the kind cluster (with the model folder mounted)
make images     # build classifier + assistant images and load them into kind
make deploy     # helm install llm, classifier, assistant into namespace "dispute"
make smoke      # send three claims to /assist and print the answers
make test       # unit tests (no cluster needed)
make down       # delete the cluster
```

---

## Done when

- [x] `make test` passes.
- [x] All three pods are `Running` and `Ready` in namespace `dispute`.
- [x] `make smoke` returns the right dispute type and a reply that quotes the right policy.
- [x] `curl localhost:8080/metrics` shows request, latency and token counters.
- [x] A tampered model file makes the classifier refuse to start.

## Interview story

> "The app talks to an OpenAI-compatible endpoint, so the same code runs against llama.cpp on my laptop, vLLM on a GPU, or a managed API behind a gateway. Only a URL changes. Prompts are versioned files, and every response records the prompt version and model that produced it. The classic model verifies its checksum before loading, because pickle files can execute code."

---

## What we saw (real results, 2026-11-13)

| Claim (hand-written) | Dispute type | Confidence | LLM time |
| --- | --- | --- | --- |
| "I was charged twice at BestElectro for 49.99" | duplicate_charge ✓ | 0.59 | 5.7 s (first request: warm-up) |
| "I cancelled my StreamMax subscription in March but they still charge me" | cancelled_recurring ✓ | 0.71 | 2.4 s |
| "A payment of 812 dollars in Lisbon that I never made" | unauthorised ✓ | 0.54 | 4.7 s |
| "The hotel charged 340 but the agreed price was 290" | incorrect_amount ✓ | 0.29 | 4.2 s |

**All four types were right, but look closer.** These findings are the reason P3 exists.

1. **A faithfulness error.** For the Lisbon claim the reply said *"issue a new one within 2 business days"*. The policy says the **temporary credit** comes within 2 business days, and doesn't give a timeline for the new card. The small model mixed two facts together. A human reviewer might miss it, so **an automated check has to catch it** (P3: faithfulness check, LLM-as-judge).
2. **Style drift.** Some replies talk about "the customer" in the third person, or just repeat the claim. The prompt says "reply to the customer"; the 0.5B model doesn't always follow it. A prompt change (v2) would fix this, **but only the eval gate can prove v2 is better and didn't break something else.**
3. **An irrelevant policy detail.** The hotel reply mentions *"no temporary credit for differences under $25"*, but the difference was $50. Not wrong, just noise.
4. **Low classifier confidence on real wording** (0.29–0.71). B2 already showed this: it was trained on template text. In production you'd route low-confidence claims to a human (a P3/P6 idea).
5. **Latency is 2–6 s per reply on CPU**, almost all of it in the LLM (`timings_ms.llm`). That's the number the GPU upgrade should cut, so we now have a baseline.
6. **A request failed during a rollout restart.** It got an empty response while the old assistant pod was shutting down. With 1 replica and no graceful shutdown, a deploy drops traffic. Fixed later with 2+ replicas, a PodDisruptionBudget, and a `preStop` delay (P4 and P10). That's a good interview detail.
7. **`/metrics` returned a 307 redirect** (a mounted sub-app adds a trailing slash). We replaced it with a plain route, so Prometheus scrapes it cleanly in P8.
