# examples/terraform/budget/variables.tf
variable "project_id" {
  description = "ID projektu kursu (np. ade-jkowalski-2611)."
  type        = string
}

variable "billing_account_id" {
  description = "ID konta rozliczeniowego w formacie XXXXXX-XXXXXX-XXXXXX (gcloud billing accounts list)."
  type        = string
}

variable "region" {
  description = "Domyślny region zasobów."
  type        = string
  default     = "europe-central2"
}

variable "owner" {
  description = "Wartość etykiety owner (małe litery, cyfry, - i _)."
  type        = string
  default     = "student"
}

variable "alert_email" {
  description = "Adres e-mail, na który trafią alerty budżetowe."
  type        = string
}

variable "monthly_budget" {
  description = "Miesięczny budżet w walucie konta rozliczeniowego (liczba całkowita)."
  type        = number
  default     = 20

  validation {
    condition     = var.monthly_budget > 0 && floor(var.monthly_budget) == var.monthly_budget
    error_message = "Budżet musi być dodatnią liczbą całkowitą."
  }
}

variable "currency_code" {
  description = "Waluta budżetu (ISO 4217). Musi być zgodna z walutą konta rozliczeniowego; null = waluta konta."
  type        = string
  default     = null
}

variable "alert_thresholds" {
  description = "Progi alertów dla faktycznych wydatków (1.0 = 100% budżetu)."
  type        = list(number)
  default     = [0.25, 0.5, 0.9, 1.0]
}

variable "bq_query_tib_per_day" {
  description = "Dzienny limit danych przetworzonych przez zapytania BigQuery w projekcie (TiB). Domyślny limit Google: 200 TiB."
  type        = number
  default     = 1
}

variable "bq_query_tib_per_user_per_day" {
  description = "Dzienny limit na użytkownika/konto serwisowe (TiB). null = bez limitu na użytkownika."
  type        = number
  default     = 0.5
}
