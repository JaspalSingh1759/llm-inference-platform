# Cost guardrails: a monthly budget with three email alerts.
resource "aws_budgets_budget" "monthly" {
  name         = "llm-platform-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Early warning: real spend passes a fixed amount (e.g. $20).
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.early_warning_usd
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  # Real spend passes the whole budget.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  # AWS predicts the month will end over budget (catches a forgotten node early).
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}

# Cost Anomaly Detection: emails a daily summary when a service's spend looks unusual,
# even if the budget isn't reached yet. Off until Cost Explorer is enabled on the account.
resource "aws_ce_anomaly_monitor" "services" {
  count             = var.enable_anomaly_detection ? 1 : 0
  name              = "llm-platform-services"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "email" {
  count            = var.enable_anomaly_detection ? 1 : 0
  name             = "llm-platform-anomalies"
  frequency        = "DAILY"
  monitor_arn_list = [aws_ce_anomaly_monitor.services[0].arn]

  subscriber {
    type    = "EMAIL"
    address = var.budget_email
  }

  # Only anomalies with at least $5 of unexpected spend.
  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = ["5"]
    }
  }
}
