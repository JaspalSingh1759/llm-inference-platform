variable "region" {
  description = "AWS region (same as the bootstrap)."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Name prefix for the cluster and everything around it."
  type        = string
  default     = "llm-platform"
}

variable "kubernetes_version" {
  description = "EKS version. One behind the newest, so add-ons and Helm charts have caught up."
  type        = string
  default     = "1.36"
}

variable "admin_cidrs" {
  description = "Who may reach the Kubernetes API (public endpoint). make eks-up passes your current IP as /32."
  type        = list(string)
}

variable "llm_instance_types" {
  description = "Spot instance types for the LLM node group: many similar 2-vCPU types = many spot pools to draw from."
  type        = list(string)
  # First session (2026-11-16): with 3 types the spot node was interrupted after 13 minutes and couldn't be
  # replaced (placement score 1-2 of 10, UnfulfillableCapacity). With these 11 the score was 9 in every zone.
  default = ["c7i.large", "c6i.large", "m7i.large", "c5.large", "c5a.large", "c6a.large", "c7a.large",
  "m5.large", "m6i.large", "m6a.large", "m7a.large"]
}

variable "gpu_enabled" {
  description = "Plan A: a GPU node group (spot g4dn, scales from 0). Off until the GPU quota is approved."
  type        = bool
  default     = false
}

variable "mlflow_db_enabled" {
  description = "RDS PostgreSQL for MLflow. Not needed until the training pipeline moves to EKS (P5)."
  type        = bool
  default     = true
}

variable "argocd_enabled" {
  description = "Install Argo CD with Helm (used for GitOps from P7)."
  type        = bool
  default     = true
}
