# Keyless CI: GitHub Actions proves who it is with a signed, short-lived OIDC token,
# and AWS hands back temporary credentials for the role below. No AWS keys are stored in GitHub.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  # e.g. repo:JaspalSingh1759@59330899/llm-inference-platform@1456772034
  github_owner   = split("/", var.github_repo)[0]
  github_name    = split("/", var.github_repo)[1]
  github_subject = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_name}@${var.github_repo_id}"
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Who may use the role: only this repo, and only from main or the approved "aws" environment.
    # A workflow on a feature branch or a fork gets a different "sub" and is refused.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "${local.github_subject}:ref:refs/heads/main",
        "${local.github_subject}:environment:aws",
      ]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name                 = "github-actions-llm-platform"
  description          = "Assumed by GitHub Actions in ${var.github_repo} via OIDC"
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

# Admin for now, to keep P0-P10 simple. P11 replaces this with least-privilege policies.
resource "aws_iam_role_policy_attachment" "github_actions_admin" {
  role       = aws_iam_role.github_actions.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
