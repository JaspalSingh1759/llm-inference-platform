# Pod Identity: a Kubernetes service account is mapped to an IAM role, and its pods get short-lived AWS
# credentials for that role. No keys in Secrets (the P2 SeaweedFS keys go away on EKS).
# Same least-privilege split as in P2: serving reads published models only; training writes them.

data "aws_iam_policy_document" "pod_identity_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

locals {
  mlops_arn  = aws_s3_bucket.this["mlops"].arn
  models_arn = aws_s3_bucket.this["models"].arn
  kms_use    = { actions = ["kms:Decrypt", "kms:GenerateDataKey"], resources = [aws_kms_key.platform.arn] }

  # namespace/service account → what its pods may do
  workloads = {
    classifier = {
      namespace = "dispute", service_account = "classifier"
      statements = [
        { actions = ["s3:GetObject"], resources = ["${local.models_arn}/dispute-classifier/*"] },
        { actions = ["s3:ListBucket"], resources = [local.models_arn] },
      ]
    }
    llm = {
      namespace = "dispute", service_account = "llm"
      statements = [
        { actions = ["s3:GetObject"], resources = ["${local.models_arn}/llm/*"] },
        { actions = ["s3:ListBucket"], resources = [local.models_arn] },
      ]
    }
    trainer = {
      namespace = "mlops", service_account = "trainer"
      statements = [
        { actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], resources = ["${local.mlops_arn}/*"] },
        { actions = ["s3:GetObject", "s3:PutObject"], resources = ["${local.models_arn}/*"] }, # publish
        { actions = ["s3:ListBucket"], resources = [local.mlops_arn, local.models_arn] },
      ]
    }
    mlflow = {
      namespace = "mlops", service_account = "mlflow"
      statements = [
        { actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], resources = ["${local.mlops_arn}/mlflow/*"] },
        { actions = ["s3:ListBucket"], resources = [local.mlops_arn] },
      ]
    }
  }
}

data "aws_iam_policy_document" "workload" {
  for_each = local.workloads
  dynamic "statement" {
    for_each = concat(each.value.statements, [local.kms_use])
    content {
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role" "workload" {
  for_each           = local.workloads
  name               = "${var.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

resource "aws_iam_role_policy" "workload" {
  for_each = local.workloads
  name     = "access"
  role     = aws_iam_role.workload[each.key].id
  policy   = data.aws_iam_policy_document.workload[each.key].json
}

# The mapping. It can exist before the namespace and service account do; it applies when they appear.
resource "aws_eks_pod_identity_association" "workload" {
  for_each        = local.workloads
  cluster_name    = module.eks.cluster_name
  namespace       = each.value.namespace
  service_account = each.value.service_account
  role_arn        = aws_iam_role.workload[each.key].arn
}

# The EBS CSI driver (an add-on) creates and attaches EBS volumes for PersistentVolumeClaims.
resource "aws_iam_role" "ebs_csi" {
  name               = "${var.name}-ebs-csi"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}
