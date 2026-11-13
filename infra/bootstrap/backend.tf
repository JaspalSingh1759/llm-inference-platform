# State lives in the bucket this stack created (moved there with terraform init -migrate-state).
# use_lockfile: Terraform 1.10+ locks with a .tflock file next to the state, no DynamoDB table needed.
terraform {
  backend "s3" {
    bucket       = "llm-platform-tfstate-352184619391"
    key          = "bootstrap/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
