# P4 platform: everything the cluster needs. Built at the start of a session and destroyed at the end
# (make eks-up / make eks-down); only the P0 bootstrap stays up.
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.70.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.3.0"
    }
  }

  # Same state bucket as the bootstrap, a different key: two stacks, applied and destroyed separately.
  backend "s3" {
    bucket       = "llm-platform-tfstate-352184619391"
    key          = "platform/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "llm-inference-platform"
      managed_by = "terraform"
      stack      = "platform"
    }
  }
}

# Helm talks to the new cluster with a short-lived token from `aws eks get-token`, never a stored kubeconfig.
provider "helm" {
  kubernetes = {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.region]
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}
