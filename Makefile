# Local (laptop) workflow for the dispute assistant. Everything runs in a kind cluster; no cloud, no cost.
CLUSTER   := llm-platform
NAMESPACE := dispute
MODEL_FILE := local/models/qwen2.5-0.5b-instruct-q4_k_m.gguf
MODEL_URL  := https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf
CHART := deploy/charts/service

.PHONY: model cluster images deploy smoke test status down

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

status:
	kubectl -n $(NAMESPACE) get pods -o wide
	@curl -s localhost:8080/status; echo

down:
	kind delete cluster --name $(CLUSTER)
