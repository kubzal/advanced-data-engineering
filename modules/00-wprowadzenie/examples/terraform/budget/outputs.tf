# examples/terraform/budget/outputs.tf
output "budget_name" {
  description = "Pełna nazwa zasobu budżetu (billingAccounts/…/budgets/…)."
  value       = google_billing_budget.monthly.name
}

output "budget_topic" {
  description = "Temat Pub/Sub z powiadomieniami o budżecie."
  value       = google_pubsub_topic.budget.id
}

output "bq_query_limit_mib_per_day" {
  description = "Dzienny limit zapytań BigQuery dla projektu (MiB)."
  value       = google_service_usage_consumer_quota_override.bq_query_per_day.override_value
}
