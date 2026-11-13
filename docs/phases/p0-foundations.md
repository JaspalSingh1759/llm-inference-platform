# P0: Foundations, the implementation plan

Part of [PLAN.md](../PLAN.md) §5. **Status (2026-11-13): done.** The bootstrap is applied and the state is in S3. The OIDC check is green. Waiting on AWS: Cost Explorer (then set `enable_anomaly_detection = true`) and the GPU appeal.

**Goal:** a safe AWS account and a connected repo, before we build anything that costs real money.

**Cost:** about $0. The S3 state bucket costs cents a month. Budgets (the first two), cost anomaly detection, IAM and OIDC are free.

---

## What we create, and why

| # | Thing | Where | Why it matters |
| --- | --- | --- | --- |
| 1 | **Local git repo**, connected to `github.com/JaspalSingh1759/llm-inference-platform` | This folder | Argo CD (P4) and GitHub Actions (P7) work from this repo |
| 2 | **Terraform state bucket** (S3) | AWS us-east-1 | Terraform's memory of what it built. Without it, Terraform can't update or destroy safely |
| 3 | **Budget alarm**: $50/month; emails at $20 actual, $50 actual, and $50 forecast | AWS Budgets | A forgotten GPU node or a leaked key can't silently run up a bill |
| 4 | **Cost anomaly detection** | AWS Cost Explorer | Emails when spending looks unusual, even below the budget |
| 5 | **GitHub OIDC provider + IAM role** `github-actions-llm-platform` | AWS IAM | GitHub Actions can deploy to AWS **without any stored keys** |
| 6 | **A test workflow** that only runs `aws sts get-caller-identity` | `.github/workflows/` | Proves (5) works end to end |

Alerts go to **jaspalsingh1759@gmail.com**.

---

## New words

| Word | Meaning |
| --- | --- |
| **Terraform state** | A JSON file listing every resource Terraform created and its real ID in AWS. Terraform compares your code with this file to decide what to add, change or delete |
| **Remote state** | Keeping that file in S3 instead of on your laptop. Your laptop and GitHub Actions then see the same state, and it survives a lost laptop |
| **State locking** | While one `terraform apply` runs, others must wait, so two runs can't corrupt the state. Terraform 1.10+ can lock with a small lock file in the same S3 bucket (`use_lockfile = true`). We have 1.10.4. Older setups used a DynamoDB table |
| **Bootstrap** | The chicken-and-egg step: Terraform needs a bucket for its state, but the bucket is created *by* Terraform. So the first apply stores state locally, then we move it into the new bucket (`terraform init -migrate-state`) |
| **OIDC (OpenID Connect)** | GitHub signs a short-lived token saying "this is workflow X in repo Y on branch Z". AWS checks the signature and hands back temporary credentials (valid about 1 hour). No secret is stored in GitHub |
| **Trust policy** | The part of an IAM role that says *who* may use it. Ours allows only this repo, and only from the `main` branch or the approved `aws` environment |
| **Least privilege** | Give only the permissions needed. P0 gives the CI role admin rights, to keep things simple; P11 narrows it. Say this honestly in interviews |

---

## Files we write

```
llm-inference-platform/
├── .gitignore                          Terraform state, .terraform/, *.tfplan, .venv, secrets never committed
└── infra/bootstrap/
    ├── versions.tf                     Terraform ≥ 1.10, AWS provider pinned
    ├── variables.tf                    region (us-east-1), budget email, GitHub repo, budget amount
    ├── state_bucket.tf                 S3 bucket: versioning, encryption, public access blocked, TLS-only, prevent_destroy
    ├── budget.tf                       monthly budget + 3 email alerts; cost anomaly monitor + subscription
    ├── github_oidc.tf                  OIDC provider + role + trust policy
    ├── outputs.tf                      bucket name, role ARN (needed in P4 and P7)
    └── backend.tf                      added after the first apply: points state at the new bucket
.github/workflows/
└── aws-oidc-check.yml                  manual trigger; assumes the role and prints the identity
```

**State bucket name:** `llm-platform-tfstate-<your account id>`. Bucket names are global across all of AWS, so the account ID keeps it unique.

**Bucket protections:**
- **Versioning:** every old state is kept, so a bad apply can be undone.
- **Encryption:** SSE-S3 (free).
- **All public access blocked.**
- **A policy that refuses non-HTTPS access.**
- **`prevent_destroy`:** Terraform refuses to delete this bucket by accident.

**The bootstrap stays up.** It's the only part we don't destroy after each session. It costs nearly nothing, and everything else depends on it.

---

## Steps, and where I ask you first

| Step | What happens | Your approval needed? |
| --- | --- | --- |
| 1 | `git init`, write `.gitignore` and the Terraform files | No (local files only) |
| 2 | `terraform init` + `terraform plan`: shows exactly what will be created, without creating anything | No (read-only) |
| 3 | **`terraform apply`**: creates the bucket, budget, anomaly monitor, OIDC provider and role | **Yes.** I show you the plan first |
| 4 | Add `backend.tf`, run `terraform init -migrate-state` to move state into the bucket | **Yes** (part of the same go) |
| 5 | You **confirm the budget/anomaly subscription emails** if AWS sends any | You do this in your inbox |
| 6 | **First commit and push** to GitHub (plan, diagrams, Terraform, workflow) | **Yes**: I only commit or push when you say so |
| 7 | Create the GitHub environment `aws` and run the check workflow | **Yes** (it's a change to your GitHub repo) |

---

## Done when

- [x] `terraform plan` in `infra/bootstrap` says **"No changes"**, using state from S3.
- [x] The budget shows in **Billing → Budgets** with 3 alerts to your email.
- [x] The **aws-oidc-check** workflow run is green and prints `assumed-role/github-actions-llm-platform/...`.
- [x] No AWS key exists anywhere in the repo or in GitHub secrets.

---

## Interview story

> "Before building anything, I set up the guardrails: a budget and cost-anomaly alerts, remote Terraform state with versioning and locking, and keyless CI with GitHub OIDC. The CI role trusts only my repo's main branch and an approved environment. There are no long-lived credentials in the pipeline, and the bootstrap is the only piece that's never torn down."

**Likely follow-ups:**
- *Why not store the state locally?* A team and CI need a shared, locked copy. Locally it gets lost or diverges.
- *Why OIDC instead of access keys in GitHub secrets?* Keys don't expire and leak easily. OIDC tokens last about an hour and are bound to a specific repo and branch.
- *How do you stop a feature branch from deploying to prod?* With the trust policy's `sub` condition: only `main` or the `aws` environment, which needs a reviewer.

---

## Before we start: one open check

**Account plan:** in the console, open **Billing and Cost Management** and check whether the account is on the **Free plan**. If it is, upgrade to the **Paid plan** before P4 (EKS and GPUs). P0 itself works on either plan.

---

## What happened (for the interview)

**The OIDC check failed at first** with `Not authorized to perform sts:AssumeRoleWithWebIdentity`.
- **How we found the cause:** CloudTrail recorded the refused call. The identity GitHub sent was `repo:JaspalSingh1759@59330899/llm-inference-platform@1456772034:environment:aws`. GitHub's `sub` claim for this repo includes the **owner ID and repo ID**, but our trust policy expected the name-only format `repo:JaspalSingh1759/llm-inference-platform:...`.
- **The fix:** pin the trust policy to the ID-based subject. We didn't loosen it with a wildcard.
- **Why the fix is safer:** with the IDs in the subject, a deleted-and-recreated repo with the same name can't use the role.
- **Lesson:** when federation fails, read the claim the identity provider actually sent (CloudTrail shows it) before touching the policy.
