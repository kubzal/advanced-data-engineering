# exercise/starter/terraform/guardrails/main.tf
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
  disable_on_destroy = false
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
    # TODO(zadanie): ogranicz budżet do tego projektu. Uwaga: projekt podaje się NUMEREM.
    # TODO(zadanie): zadbaj, żeby kredyty (trial, Free Tier) nie ukrywały kosztów.
    calendar_period = "MONTH"
  }

  amount {
    specified_amount {
      currency_code = var.currency_code
      units         = tostring(var.monthly_budget)
    }
  }

  # TODO(zadanie): co najmniej trzy progi wydatków faktycznych (np. 25%, 50%, 90%, 100%)
  #                i jeden próg dla prognozy (FORECASTED_SPEND).

  # TODO(zadanie): blok all_updates_rule, który podłącza kanał e-mail i temat Pub/Sub
  #                utworzone wyżej (schema_version = "1.0").

  depends_on = [google_project_service.apis]
}

# TODO(zadanie): dwa nadpisania limitów BigQuery (provider google-beta,
# zasób google_service_usage_consumer_quota_override):
#   - QueryUsagePerDay:        metryka bigquery.googleapis.com/quota/query/usage, limit /d/project
#   - QueryUsagePerUserPerDay: ta sama metryka, limit /d/project/user
# Wartości: var.bq_query_tib_per_day i var.bq_query_tib_per_user_per_day przeliczone na MiB.
# Pamiętaj o urlencode() dla metryki i limitu.
