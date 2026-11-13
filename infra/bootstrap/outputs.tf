output "state_bucket" {
  description = "S3 bucket holding Terraform state for every stack."
  value       = aws_s3_bucket.tfstate.bucket
}

output "github_actions_role_arn" {
  description = "Role GitHub Actions assumes (set as the AWS_ROLE_ARN repo variable)."
  value       = aws_iam_role.github_actions.arn
}
