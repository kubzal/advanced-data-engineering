# exercise/solution/terraform/guardrails/main.tf
#
# Bezpieczniki projektu: zostają na CAŁY kurs (osobny stan Terraform niż dane modułu).

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  mib_per_tib = 1048576
}

resource "google_project_service" "apis" {
  for_each = toset([
    "bigquery.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbilling.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false # wyłączanie API przy destroy psułoby zasoby z innych stanów
}

resource "google_monitoring_notification_channel" "budget_email" {
  display_name = "ADE: alerty budżetowe"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
  user_labels = local.labels
  depends_on  = [google_project_service.apis]
}

resource "google_pubsub_topic" "budget" {
  name                       = "billing-budget-notifications"
  message_retention_duration = "604800s"
  depends_on                 = [google_project_service.apis]
}

resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account_id
  display_name    = "ade-${var.project_id}-monthly"

  budget_filter {
    projects               = ["projects/${data.google_project.this.number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
    calendar_period        = "MONTH"
  }

  amount {
    specified_amount {
      currency_code = var.currency_code
      units         = tostring(var.monthly_budget)
    }
  }

  dynamic "threshold_rules" {
    for_each = [0.25, 0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.budget_email.id]
    pubsub_topic                     = google_pubsub_topic.budget.id
    schema_version                   = "1.0"
  }

  depends_on = [google_project_service.apis]
}

# Custom quotas BigQuery. Wartość w MiB; sprawdź po apply w konsoli (Quotas & System Limits).
resource "google_service_usage_consumer_quota_override" "bq_query_per_day" {
  provider       = google-beta
  project        = var.project_id
  service        = "bigquery.googleapis.com"
  metric         = urlencode("bigquery.googleapis.com/quota/query/usage")
  limit          = urlencode("/d/project")
  override_value = tostring(floor(var.bq_query_tib_per_day * local.mib_per_tib))
  force          = true
  depends_on     = [google_project_service.apis]
}

resource "google_service_usage_consumer_quota_override" "bq_query_per_user_per_day" {
  provider       = google-beta
  project        = var.project_id
  service        = "bigquery.googleapis.com"
  metric         = urlencode("bigquery.googleapis.com/quota/query/usage")
  limit          = urlencode("/d/project/user")
  override_value = tostring(floor(var.bq_query_tib_per_user_per_day * local.mib_per_tib))
  force          = true
  depends_on     = [google_project_service.apis]
}
