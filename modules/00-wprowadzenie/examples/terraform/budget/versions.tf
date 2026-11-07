# examples/terraform/budget/versions.tf
terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
    # Nadpisanie limitu (quota override) jest dostępne tylko w providerze google-beta.
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 8.0"
    }
  }
}

locals {
  labels = {
    course = "ade"
    module = "00"
    owner  = var.owner
  }
}

# Billing Budgets API wymaga wskazania projektu, który „płaci” za wywołania API
# (quota project). Przy uwierzytelnieniu kontem użytkownika (ADC z gcloud) bez tych
# dwóch ustawień API zwraca 403.
provider "google" {
  project               = var.project_id
  region                = var.region
  billing_project       = var.project_id
  user_project_override = true
  default_labels        = local.labels
}

provider "google-beta" {
  project               = var.project_id
  region                = var.region
  billing_project       = var.project_id
  user_project_override = true
  default_labels        = local.labels
}
