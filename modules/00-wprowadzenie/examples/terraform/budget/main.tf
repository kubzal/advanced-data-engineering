# examples/terraform/budget/main.tf
#
# Bezpieczniki kosztowe projektu kursu:
#   1. budżet miesięczny z alertami e-mail (progi faktyczne + prognoza),
#   2. temat Pub/Sub z powiadomieniami programowymi (podstawa automatyzacji),
#   3. dzienne limity (custom quotas) na bajty przetwarzane przez zapytania BigQuery.
#
# Budżet NIE zatrzymuje wydatków. Zatrzymują je dopiero limity z punktu 3
# (tylko dla zapytań BigQuery on-demand) albo Twoja reakcja na alert.

data "google_project" "this" {
  project_id = var.project_id
}

# --- 1. Kanał powiadomień e-mail ------------------------------------------------
resource "google_monitoring_notification_channel" "budget_email" {
  display_name = "ADE: alerty budżetowe"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
  user_labels = local.labels
}

# --- 2. Temat Pub/Sub na powiadomienia programowe -------------------------------
# Cloud Billing publikuje tu stan budżetu kilka razy dziennie (nie tylko po
# przekroczeniu progu). Subskrybent może np. wysłać wiadomość na Slacka albo
# wyłączyć billing projektu (lekcja 00.03, sekcja o „bezpieczniku”).
resource "google_pubsub_topic" "budget" {
  name                       = "billing-budget-notifications"
  message_retention_duration = "604800s" # 7 dni: można odtworzyć historię alertów
}

# --- 3. Budżet --------------------------------------------------------------------
resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account_id
  display_name    = "ade-${var.project_id}-monthly"

  budget_filter {
    # Projekt wskazujemy NUMEREM, nie identyfikatorem.
    projects = ["projects/${data.google_project.this.number}"]

    # Kredyty (free trial, Free Tier, promocje) NIE pomniejszają wydatków budżetu.
    # Bez tego w okresie próbnym „wydatki” wynoszą 0 i alert nigdy nie przychodzi,
    # dopóki kredyty się nie skończą.
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
    for_each = var.alert_thresholds
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  # Prognoza: alert, gdy przy obecnym tempie wydatków miesiąc skończy się powyżej budżetu.
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.budget_email.id]
    pubsub_topic                     = google_pubsub_topic.budget.id
    schema_version                   = "1.0"
    # Domyślni odbiorcy (administratorzy i użytkownicy konta rozliczeniowego) też dostaną e-mail.
    disable_default_iam_recipients = false
  }
}

# --- 4. Custom quotas BigQuery ----------------------------------------------------
# Metryka: bigquery.googleapis.com/quota/query/usage (quota ID: QueryUsagePerDay
# i QueryUsagePerUserPerDay). Limity dotyczą tylko zapytań on-demand, są
# przybliżone i zerują się o północy czasu pacyficznego (PT).
#
# Wartość nadpisania podajemy w MiB (1 TiB = 1 048 576 MiB). Jednostkę sprawdzisz po
# `terraform apply` w konsoli: IAM & Admin → Quotas & System Limits → BigQuery API.
locals {
  mib_per_tib = 1048576
}

resource "google_service_usage_consumer_quota_override" "bq_query_per_day" {
  provider       = google-beta
  project        = var.project_id
  service        = "bigquery.googleapis.com"
  metric         = urlencode("bigquery.googleapis.com/quota/query/usage")
  limit          = urlencode("/d/project")
  override_value = tostring(floor(var.bq_query_tib_per_day * local.mib_per_tib))
  # Obniżenie limitu o więcej niż 10% wymaga potwierdzenia (force).
  force = true
}

resource "google_service_usage_consumer_quota_override" "bq_query_per_user_per_day" {
  count          = var.bq_query_tib_per_user_per_day == null ? 0 : 1
  provider       = google-beta
  project        = var.project_id
  service        = "bigquery.googleapis.com"
  metric         = urlencode("bigquery.googleapis.com/quota/query/usage")
  limit          = urlencode("/d/project/user")
  override_value = tostring(floor(var.bq_query_tib_per_user_per_day * local.mib_per_tib))
  force          = true
}
