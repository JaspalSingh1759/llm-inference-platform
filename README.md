# LLM inference platform

An LLM (vLLM on a GPU) and a classic ML model (scikit-learn on CPU), served on AWS EKS with KServe, behind a gateway with guardrails. Shipped by an eval-gated GitOps pipeline and watched with Prometheus, Grafana and OpenTelemetry tracing. All infrastructure is Terraform.

Use case: a fictional bank's dispute assistant (synthetic data only).

- Plan: [docs/PLAN.md](docs/PLAN.md)
- Diagrams: `cd docs/diagrams && python3 make_diagrams.py .`

## Progress

- [ ] P0 Foundations
- [ ] P1 Local LLM app
- [ ] P2 Eval + tracing
- [ ] P3 Terraform (EKS, GPU nodes)
- [ ] P4 GPU serving (KServe + vLLM)
- [ ] P5 Gateway + guardrails
- [ ] P6 CI/CD with eval gate
- [ ] P7 Observability
- [ ] P8 Scale + cost
- [ ] P9 Safe rollouts
- [ ] P10 Security
- [ ] P11 Incident drills
- [ ] P12 SageMaker comparison (optional)
