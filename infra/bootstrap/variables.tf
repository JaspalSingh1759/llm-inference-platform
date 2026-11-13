variable "region" {
  description = "AWS region for the whole project."
  type        = string
  default     = "us-east-1"
}

variable "budget_email" {
  description = "Where budget alerts go. Set in terraform.tfvars (not committed)."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget. Alerts fire at the early warning amount, at 100% actual and at 100% forecast."
  type        = number
  default     = 50
}

variable "early_warning_usd" {
  description = "First alert, as an absolute amount spent this month."
  type        = number
  default     = 20
}

variable "enable_anomaly_detection" {
  description = "Cost Anomaly Detection needs Cost Explorer enabled on the account first (takes up to 24 hours)."
  type        = bool
  default     = false
}

variable "github_repo" {
  description = "owner/name of the repo whose GitHub Actions may use the CI role."
  type        = string
  default     = "JaspalSingh1759/llm-inference-platform"
}
