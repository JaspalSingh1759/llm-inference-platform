# P0 bootstrap: the few resources everything else depends on. Applied once from a laptop and never destroyed.
terraform {
  required_version = ">= 1.10" # 1.10+ can lock state with a lock file in S3 (no DynamoDB table needed)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  # Every resource gets these tags, so cost and ownership are easy to trace.
  default_tags {
    tags = {
      project    = "llm-inference-platform"
      managed_by = "terraform"
      stack      = "bootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}
