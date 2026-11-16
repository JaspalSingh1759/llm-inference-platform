# Storage: one KMS key, the two S3 buckets the P2 pipeline used in SeaweedFS, and container registries.

# One customer-managed key for this stack: S3 objects, Kubernetes Secrets, RDS. $1/month while it exists;
# after destroy it waits 7 days (no charge while pending deletion), then is gone.
resource "aws_kms_key" "platform" {
  description             = "${var.name}: S3, EKS secrets, RDS"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "platform" {
  name          = "alias/${var.name}"
  target_key_id = aws_kms_key.platform.key_id
}

# Same layout as SeaweedFS in P2: mlops (raw/, datasets/, mlflow/, argo/) and models (published models,
# plus llm/ for LLM weights in P5). Serving can only read models.
locals {
  buckets = {
    mlops  = "${var.name}-mlops-${data.aws_caller_identity.current.account_id}"
    models = "${var.name}-models-${data.aws_caller_identity.current.account_id}"
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets
  bucket   = each.value
  # Lab setting: destroy deletes the contents too. Production: false, so a destroy can't wipe models.
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  versioning_configuration { status = "Enabled" } # an overwritten or deleted model can be recovered
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.platform.arn
    }
    bucket_key_enabled = true # fewer KMS calls, lower cost
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Old versions of overwritten objects are kept 30 days, then deleted, so versioning doesn't grow forever.
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

# Container registries for our images (and, later, mirrored third-party images: see the P2 MinIO finding).
resource "aws_ecr_repository" "this" {
  for_each             = toset(["assistant", "classifier", "trainer", "mlflow"])
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE" # a tag always means the same image; deploys use the git SHA
  force_delete         = true        # lab: destroy removes the images too

  image_scanning_configuration { scan_on_push = true }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.platform.arn
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 20 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }
      action       = { type = "expire" }
    }]
  })
}
