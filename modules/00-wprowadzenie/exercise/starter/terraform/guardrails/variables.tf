# exercise/starter/terraform/guardrails/variables.tf
variable "project_id" {
  description = "ID projektu kursu."
  type        = string
}

variable "billing_account_id" {
  description = "ID konta rozliczeniowego (XXXXXX-XXXXXX-XXXXXX)."
  type        = string
}

variable "region" {
  description = "Domyślny region."
  type        = string
  default     = "europe-central2"
}

variable "owner" {
  description = "Wartość etykiety owner."
  type        = string
  default     = "student"
}

variable "alert_email" {
  description = "Adres e-mail na alerty budżetowe."
  type        = string
}

variable "monthly_budget" {
  description = "Miesięczny budżet w walucie konta rozliczeniowego."
  type        = number
  default     = 20
}

variable "currency_code" {
  description = "Waluta budżetu; null = waluta konta rozliczeniowego."
  type        = string
  default     = null
}

variable "bq_query_tib_per_day" {
  description = "Limit QueryUsagePerDay (TiB/dzień)."
  type        = number
  default     = 1
}

variable "bq_query_tib_per_user_per_day" {
  description = "Limit QueryUsagePerUserPerDay (TiB/dzień)."
  type        = number
  default     = 0.5
}
