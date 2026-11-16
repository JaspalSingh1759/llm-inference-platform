# Argo CD, installed by Terraform so the cluster comes up ready for GitOps (P7 points it at this repo).
# Small footprint for a lab: no Dex (SSO, P11), no notifications, one replica of each part.
resource "helm_release" "argocd" {
  count            = var.argocd_enabled ? 1 : 0
  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = "10.11.6"
  timeout          = 600

  values = [yamlencode({
    global = {
      nodeSelector = { "node-role" = "system" }
    }
    configs = {
      params = { "server.insecure" = true } # TLS ends at kubectl port-forward locally; an ingress in P11
    }
    dex           = { enabled = false }
    notifications = { enabled = false }
  })]

  # The node groups must exist, or the pods have nowhere to run and the release times out.
  depends_on = [module.eks]
}
