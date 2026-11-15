# Local (laptop) workflow for the dispute assistant. Everything runs in a kind cluster; no cloud, no cost.
CLUSTER   := llm-platform
NAMESPACE := dispute
MODEL_FILE := local/models/qwen2.5-0.5b-instruct-q4_k_m.gguf
MODEL_URL  := https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf
CHART := deploy/charts/service
# P2 training pipeline
B2_DATA ?= ../microsoft-agent-framework-foundry-starter-pack-net/mlops/data-pipeline/data
ARGO_CHART_VERSION := 2.0.13
GIT_COMMIT := $(shell git rev-parse --short HEAD)$(shell git diff --quiet HEAD -- training || echo -dirty)
RAW ?= claims-2026-11.csv

.PHONY: model cluster images deploy smoke test status down mlops mlops-images mlops-reset raw-drops train runs ui tracing eval

model: $(MODEL_FILE)
$(MODEL_FILE):
	curl -L --fail -o $@.part $(MODEL_URL) && mv $@.part $@

cluster: $(MODEL_FILE)
	MODELS_DIR=$(CURDIR)/local/models envsubst < local/kind-config.yaml.tpl > local/kind-config.yaml
	kind get clusters | grep -qx $(CLUSTER) || kind create cluster --name $(CLUSTER) --config local/kind-config.yaml

images:
	docker build -t classifier:dev models/classifier
	docker build -t assistant:dev app
	kind load docker-image classifier:dev assistant:dev --name $(CLUSTER)

# --- P2: training pipeline -------------------------------------------------------------------------
mlops-images:
	docker build -t trainer:dev --build-arg GIT_COMMIT=$(GIT_COMMIT) training
	docker build -t mlflow:dev training/mlflow
	kind load docker-image trainer:dev mlflow:dev --name $(CLUSTER)

# Storage (SeaweedFS as S3), PostgreSQL, MLflow, Argo Workflows and the pipeline template.
mlops: mlops-images
	training/scripts/secrets.sh
	kubectl apply -f training/mlops.yaml
	kubectl -n mlops rollout status deploy/s3 deploy/postgres --timeout=180s
	training/scripts/buckets.sh
	helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
	helm upgrade --install argo-workflows argo/argo-workflows --version $(ARGO_CHART_VERSION) \
	  -n argo --create-namespace -f training/argo-values.yaml --wait
	kubectl -n mlops rollout status deploy/mlflow --timeout=180s
	kubectl apply -f training/workflow.yaml

# Plays the data team: B2 datasets → raw CSV exports (with duplicates and messy rows) → s3://mlops/raw/
raw-drops:
	mkdir -p training/raw
	docker run --rm -v "$(abspath $(B2_DATA))":/in:ro -v "$(CURDIR)/training/raw":/out trainer:dev \
	  python tools/make_raw_drops.py /in /out
	training/scripts/upload_raw.sh

# One pipeline run: make train RAW=claims-2026-11.csv
train:
	training/scripts/train.sh $(RAW)

runs:
	kubectl -n mlops get workflows

# Local only: forget all training history (runs, MLflow, datasets, published models); raw drops stay.
mlops-reset:
	training/scripts/reset.sh

# Argo on http://localhost:2746, MLflow on http://localhost:5000, Phoenix on http://localhost:6006 (Ctrl-C to stop)
ui:
	kubectl -n argo port-forward svc/argo-workflows-server 2746:2746 & \
	kubectl -n observability port-forward svc/phoenix 6006:6006 & \
	kubectl -n mlops port-forward svc/mlflow 5000:5000; kill %1 %2

# --- P3: evaluation and tracing ----------------------------------------------------------------------
tracing:
	kubectl apply -f local/phoenix.yaml
	kubectl -n observability rollout status deploy/phoenix --timeout=300s

# Golden set against the running assistant: make eval; a candidate prompt: make eval PROMPT=v2
eval:
	evals/eval.sh $(PROMPT)

deploy:
	for svc in llm classifier assistant; do \
	  helm upgrade --install $$svc $(CHART) -f deploy/local/$$svc.yaml -n $(NAMESPACE) --create-namespace || exit 1; \
	done
	kubectl -n $(NAMESPACE) rollout status deploy/classifier deploy/assistant --timeout=120s
	kubectl -n $(NAMESPACE) rollout status deploy/llm --timeout=300s

smoke:
	@for claim in \
	  "I was charged twice at BestElectro for 49.99 on my card" \
	  "I cancelled my StreamMax subscription in March but they still charge me every month" \
	  "There is a payment of 812 dollars at a store in Lisbon that I never made"; do \
	  echo "\n> $$claim"; \
	  curl -s --max-time 60 localhost:8080/assist -H 'content-type: application/json' -d "{\"text\": \"$$claim\"}" | python3 -m json.tool; \
	done

test:
	cd app && ../.venv/bin/python -m pytest -q tests
	cd models/classifier && ../../.venv/bin/python -m pytest -q tests
	docker run --rm -v "$(CURDIR)/training/tests":/app/tests:ro trainer:dev python -m pytest -q -p no:cacheprovider tests
	cd evals && ../.venv/bin/python -m pytest -q tests

status:
	kubectl -n $(NAMESPACE) get pods -o wide
	@curl -s localhost:8080/status; echo

down:
	kind delete cluster --name $(CLUSTER)
