# exercise/solution/terraform/guardrails/outputs.tf
output "project_number" {
  value = data.google_project.this.number
}

output "budget_name" {
  value = google_billing_budget.monthly.name
}

output "budget_topic" {
  value = google_pubsub_topic.budget.id
}

output "bq_query_limit_mib_per_day" {
  value = google_service_usage_consumer_quota_override.bq_query_per_day.override_value
}

output "bq_query_limit_mib_per_user_per_day" {
  value = google_service_usage_consumer_quota_override.bq_query_per_user_per_day.override_value
}
