#!/usr/bin/env bash
# examples/01_bootstrap_project.sh
#
# Tworzy projekt GCP dla kursu, podpina go do konta rozliczeniowego i włącza potrzebne API.
# Skrypt jest idempotentny: ponowne uruchomienie pomija kroki, które są już wykonane.
#
# Użycie:
#   export PROJECT_ID="ade-jkowalski-2611"        # globalnie unikalny, 6–30 znaków, [a-z0-9-]
#   export BILLING_ACCOUNT="0X0X0X-0X0X0X-0X0X0X"  # gcloud billing accounts list
#   ./01_bootstrap_project.sh
#
# Opcjonalnie:
#   REGION=europe-central2      domyślny region zasobów (Warszawa)
#   PARENT=folders/123456789    lub organizations/123456789; puste = projekt bez organizacji
#   OWNER_LABEL=jkowalski       wartość etykiety owner (małe litery, cyfry, - i _)
set -euo pipefail

: "${PROJECT_ID:?Ustaw PROJECT_ID, np. export PROJECT_ID=ade-twojelogin-$(date +%y%m)}"
: "${BILLING_ACCOUNT:?Ustaw BILLING_ACCOUNT, listę kont pokaże: gcloud billing accounts list}"
REGION="${REGION:-europe-central2}"
PARENT="${PARENT:-}"
OWNER_LABEL="${OWNER_LABEL:-student}"
LABELS="course=ade,module=00,owner=${OWNER_LABEL}"

# API potrzebne w module 00. Kolejne moduły włączają swoje API same (Terraform: google_project_service).
APIS=(
  cloudresourcemanager.googleapis.com  # zarządzanie projektem
  serviceusage.googleapis.com          # włączanie API i limity (quotas)
  cloudbilling.googleapis.com          # powiązanie projektu z kontem rozliczeniowym
  billingbudgets.googleapis.com        # budżety i alerty
  monitoring.googleapis.com            # kanały powiadomień (e-mail)
  pubsub.googleapis.com                # powiadomienia programowe o budżecie
  bigquery.googleapis.com
  storage.googleapis.com
)

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# 1. Projekt -------------------------------------------------------------------
if gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  log "Projekt ${PROJECT_ID} już istnieje, pomijam tworzenie."
else
  create_args=(--name="Advanced Data Engineering" --labels="$LABELS")
  case "$PARENT" in
    folders/*)       create_args+=(--folder="${PARENT#folders/}") ;;
    organizations/*) create_args+=(--organization="${PARENT#organizations/}") ;;
    "")              ;;
    *) echo "PARENT musi mieć postać folders/ID albo organizations/ID" >&2; exit 1 ;;
  esac
  log "Tworzę projekt ${PROJECT_ID}"
  gcloud projects create "$PROJECT_ID" "${create_args[@]}"
fi

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

# 2. Billing -------------------------------------------------------------------
current_billing="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingAccountName)')"
if [[ "$current_billing" == "billingAccounts/${BILLING_ACCOUNT}" ]]; then
  log "Projekt jest już podpięty do konta rozliczeniowego ${BILLING_ACCOUNT}."
else
  log "Podpinam projekt do konta rozliczeniowego ${BILLING_ACCOUNT}"
  gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
fi

# 3. API -----------------------------------------------------------------------
# `services enable` jest idempotentne: włączone API zostaną pominięte.
log "Włączam API (może potrwać 1–2 minuty)"
gcloud services enable "${APIS[@]}" --project="$PROJECT_ID"

# 4. Podsumowanie --------------------------------------------------------------
cat <<SUMMARY

Gotowe.
  Project ID:      ${PROJECT_ID}
  Project number:  ${PROJECT_NUMBER}
  Billing account: ${BILLING_ACCOUNT}
  Region:          ${REGION}
  Etykiety:        ${LABELS}

Następne kroki (skrypt celowo NIE zmienia Twojej konfiguracji gcloud):
  gcloud config configurations create ade
  gcloud config set project ${PROJECT_ID}
  gcloud config set compute/region ${REGION}
  gcloud auth application-default set-quota-project ${PROJECT_ID}

Potem od razu ustaw budżet: examples/terraform/budget (lekcja 00.03).
SUMMARY
