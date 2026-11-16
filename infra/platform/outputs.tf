output "cluster_name" {
  value = module.eks.cluster_name
}

output "kubeconfig_command" {
  description = "Adds the cluster to ~/.kube/config (make eks-kubeconfig runs it)."
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region} --alias ${var.name}-eks"
}

output "ecr_repositories" {
  value = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}

output "buckets" {
  value = { for k, b in aws_s3_bucket.this : k => b.bucket }
}

output "workload_roles" {
  description = "IAM role per namespace/service account (Pod Identity)."
  value       = { for k, w in local.workloads : "${w.namespace}/${w.service_account}" => aws_iam_role.workload[k].arn }
}

output "mlflow_db_endpoint" {
  value = var.mlflow_db_enabled ? aws_db_instance.mlflow[0].endpoint : null
}

output "mlflow_db_secret_arn" {
  description = "Secrets Manager secret holding the database password (created by RDS)."
  value       = var.mlflow_db_enabled ? aws_db_instance.mlflow[0].master_user_secret[0].secret_arn : null
}
