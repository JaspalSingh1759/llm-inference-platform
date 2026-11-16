# EKS: the control plane (run by AWS) plus four managed node groups, each for one kind of work.
#   system  on-demand, always 2 nodes: cluster add-ons, Argo CD, the assistant, the classifier
#   llm     spot, tainted: only pods that tolerate the taint (the LLM server) land here
#   training spot, tainted: pipeline pods (Argo Workflows); interrupted steps are retried
#   gpu     spot g4dn, tainted, scales from 0: Plan A, off until the GPU quota is approved
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.29.0"

  name               = var.name
  kubernetes_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets # nodes live in private subnets

  # The API is public but only reachable from admin_cidrs (your IP). P11: private endpoint + VPN/bastion.
  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.admin_cidrs

  # Access entries (the EKS API) instead of the old aws-auth ConfigMap; whoever runs apply is cluster admin.
  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = true

  # Kubernetes Secrets are encrypted with our KMS key (envelope encryption).
  create_kms_key    = false
  encryption_config = { provider_key_arn = aws_kms_key.platform.arn, resources = ["secrets"] }

  # Who did what to the cluster: audit logs to CloudWatch, kept a week (a lab, not an audit trail).
  enabled_log_types                      = ["audit"]
  cloudwatch_log_group_retention_in_days = 7

  addons = {
    vpc-cni                = { before_compute = true } # pod networking: must exist before nodes join
    eks-pod-identity-agent = { before_compute = true } # lets pods get IAM roles (Pod Identity)
    kube-proxy             = {}
    coredns                = {}
    aws-ebs-csi-driver = { # PersistentVolumes on EBS (Phoenix, caches in P5)
      pod_identity_association = [{ role_arn = aws_iam_role.ebs_csi.arn, service_account = "ebs-csi-controller-sa" }]
    }
  }

  eks_managed_node_groups = merge(
    {
      system = {
        ami_type       = "AL2023_x86_64_STANDARD"
        instance_types = ["t3.large"] # 2 vCPU, 8 GiB
        capacity_type  = "ON_DEMAND"  # add-ons and Argo CD shouldn't vanish on a spot interruption
        min_size       = 2
        max_size       = 2
        desired_size   = 2
        labels         = { "node-role" = "system" }
      }

      llm = {
        ami_type       = "AL2023_x86_64_STANDARD"
        instance_types = var.llm_instance_types
        capacity_type  = "SPOT" # ~70% cheaper; an interruption reschedules the LLM pod (P12 drill)
        min_size       = 1
        max_size       = 2
        desired_size   = 1
        labels         = { "node-role" = "llm" }
        # The taint keeps everything else off; the LLM pod tolerates it and selects node-role=llm.
        taints = { llm = { key = "workload", value = "llm", effect = "NO_SCHEDULE" } }
      }

      training = {
        ami_type       = "AL2023_x86_64_STANDARD"
        instance_types = var.llm_instance_types # same wide spot pool
        capacity_type  = "SPOT"                 # training is retryable: the cheapest capacity there is
        # 1 node while the cluster is up. Scaling from 0 when a run starts needs an autoscaler (Karpenter, P9).
        min_size     = 0
        max_size     = 1
        desired_size = 1
        labels       = { "node-role" = "training" }
        taints       = { training = { key = "workload", value = "training", effect = "NO_SCHEDULE" } }
      }
    },
    var.gpu_enabled ? {
      gpu = {
        ami_type       = "AL2023_x86_64_NVIDIA" # EKS accelerated AMI: NVIDIA driver + container toolkit
        instance_types = ["g4dn.xlarge"]        # 1× NVIDIA T4 (16 GB), 4 vCPU
        capacity_type  = "SPOT"
        min_size       = 0 # no GPU, no cost: a GPU pod scales it up (P9 Karpenter/autoscaler)
        max_size       = 1
        desired_size   = 0
        labels         = { "node-role" = "gpu" }
        taints         = { gpu = { key = "nvidia.com/gpu", value = "true", effect = "NO_SCHEDULE" } }
        block_device_mappings = { # vLLM images and model weights need more than the default 20 GiB
          xvda = { device_name = "/dev/xvda", ebs = { volume_size = 80, volume_type = "gp3", encrypted = true } }
        }
      }
    } : {}
  )
}
