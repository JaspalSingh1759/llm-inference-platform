# LLM inference platform

An LLM (vLLM on a GPU) and a classic ML model (scikit-learn on CPU), served on AWS EKS with KServe, behind a gateway with guardrails, with a training pipeline that retrains the classic model in pods. Shipped by an eval-gated GitOps pipeline and watched with Prometheus, Grafana and OpenTelemetry tracing. All infrastructure is Terraform.

Use case: a fictional bank's dispute assistant (synthetic data only).

- Plan: [docs/PLAN.md](docs/PLAN.md)
- Diagrams: `cd docs/diagrams && python3 make_diagrams.py .`

## Progress

- [x] P0 Foundations
- [x] P1 Local LLM app
- [ ] P2 Training pipeline (Argo Workflows, MLflow, retrain → gate → serve)
- [ ] P3 Eval + tracing
- [ ] P4 Terraform (EKS, node groups)
- [ ] P5 LLM serving (KServe: llama.cpp on CPU now, vLLM on GPU later)
- [ ] P6 Gateway + guardrails
- [ ] P7 CI/CD with eval gate
- [ ] P8 Observability
- [ ] P9 Scale + cost
- [ ] P10 Safe rollouts
- [ ] P11 Security
- [ ] P12 Incident drills
- [ ] P13 SageMaker comparison (optional)
