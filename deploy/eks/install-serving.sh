#!/usr/bin/env bash
# P5: installs the serving layer on EKS: cert-manager (certificates for KServe's webhooks) and KServe in
# Standard mode (plain Deployments + Services, no Knative/Istio). Pinned versions; safe to re-run.
# P7 moves these into Argo CD.
set -euo pipefail
CERT_MANAGER_VERSION=v1.21.3
KSERVE_VERSION=v0.21.0

helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
helm repo update jetstack >/dev/null
helm upgrade --install cert-manager jetstack/cert-manager --version $CERT_MANAGER_VERSION \
  -n cert-manager --create-namespace --wait \
  --set crds.enabled=true --set nodeSelector.node-role=system \
  --set webhook.nodeSelector.node-role=system --set cainjector.nodeSelector.node-role=system

helm upgrade --install kserve-crd oci://ghcr.io/kserve/charts/kserve-crd --version $KSERVE_VERSION \
  -n kserve --create-namespace --wait
helm upgrade --install kserve oci://ghcr.io/kserve/charts/kserve-resources --version $KSERVE_VERSION \
  -n kserve --wait \
  --set kserve.controller.deploymentMode=Standard \
  --set kserve.controller.gateway.disableIngressCreation=true \
  --set kserve.controller.gateway.disableIstioVirtualHost=true   # no Istio here: plain Services
kubectl -n kserve get pods
