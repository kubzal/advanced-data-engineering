# exercise/starter/terraform/guardrails/outputs.tf
output "project_number" {
  value = data.google_project.this.number
}

output "budget_name" {
  value = google_billing_budget.monthly.name
}

output "budget_topic" {
  value = google_pubsub_topic.budget.id
}

# TODO(zadanie): dodaj outputy z wartościami nadpisanych limitów BigQuery (MiB).
