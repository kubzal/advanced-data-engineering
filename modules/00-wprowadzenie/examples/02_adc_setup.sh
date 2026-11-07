#!/usr/bin/env bash
# examples/02_adc_setup.sh
# Konfiguruje osobną konfigurację gcloud dla kursu i Application Default Credentials (ADC)
# z impersonacją konta serwisowego, bez kluczy JSON.
#
# Użycie:
#   PROJECT_ID=novacart-dev-1234 bash examples/02_adc_setup.sh
#   PROJECT_ID=novacart-dev-1234 SA_NAME=ade-runner bash examples/02_adc_setup.sh --impersonate
#
# Skrypt NIE wypisuje tokenów. Pokazuje wyłącznie ich metadane (typ, właściciel, czas ważności).

set -euo pipefail

: "${PROJECT_ID:?Ustaw PROJECT_ID, np. PROJECT_ID=novacart-dev-1234}"
CONFIG_NAME="${CONFIG_NAME:-ade}"
REGION="${REGION:-europe-west4}"
SA_NAME="${SA_NAME:-ade-runner}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
IMPERSONATE=false
[[ "${1:-}" == "--impersonate" ]] && IMPERSONATE=true

step() { printf '\n== %s ==\n' "$*"; }

# --- 1. Osobna konfiguracja gcloud dla kursu --------------------------------------------
# Konfiguracja to nazwany zestaw ustawień (konto, projekt, region). Dzięki niej kurs
# nie miesza się z projektami z pracy: przełączasz się jednym poleceniem.
step "1. Konfiguracja gcloud '${CONFIG_NAME}'"
if ! gcloud config configurations describe "$CONFIG_NAME" >/dev/null 2>&1; then
  gcloud config configurations create "$CONFIG_NAME" --no-activate
fi
gcloud config configurations activate "$CONFIG_NAME"
gcloud config set project "$PROJECT_ID"
gcloud config set compute/region "$REGION"
gcloud config set compute/zone "${REGION}-a"

# --- 2. Logowanie dla gcloud (poświadczenia CLI) ----------------------------------------
# Te poświadczenia trafiają do bazy gcloud i są używane przez polecenia gcloud/bq.
# NIE są widoczne dla Twojego kodu w Pythonie ani dla Terraform.
step "2. gcloud auth login (poświadczenia CLI)"
if [[ -z "$(gcloud config get-value account 2>/dev/null)" ]]; then
  gcloud auth login --update-adc=false
fi
gcloud config get-value account

# --- 3. ADC dla bibliotek klienckich i Terraform -----------------------------------------
# Osobny plik: ~/.config/gcloud/application_default_credentials.json
step "3. Application Default Credentials"
if $IMPERSONATE; then
  # Twój użytkownik musi mieć roles/iam.serviceAccountTokenCreator na koncie serwisowym.
  # Plik ADC zawiera wtedy Twój refresh token + adres SA; biblioteki same wymieniają go
  # na krótkotrwały token konta serwisowego (domyślnie ważny 1 h).
  gcloud auth application-default login --impersonate-service-account="$SA_EMAIL"
else
  gcloud auth application-default login
  # Projekt, który płaci za limity (quota) i do którego trafiają wywołania API
  # „bez projektu” (np. niektóre wywołania Service Usage). Tylko dla poświadczeń użytkownika.
  gcloud auth application-default set-quota-project "$PROJECT_ID"
fi

# --- 4. Co jest w pliku ADC? (bez sekretów) ----------------------------------------------
step "4. Typ poświadczeń w pliku ADC"
ADC_FILE="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}/application_default_credentials.json"
python3 - "$ADC_FILE" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
safe = {k: v for k, v in data.items() if k in {"type", "quota_project_id", "service_account_impersonation_url"}}
print(json.dumps(safe, indent=2))   # client_secret i refresh_token celowo pomijamy
PY

# --- 4b. Co widzi biblioteka kliencka? ---------------------------------------------------
# google.auth.default() to ten sam algorytm ADC, którego używają google-cloud-* i Terraform.
step "4b. google.auth.default() z perspektywy Pythona"
(cd "$(dirname "${BASH_SOURCE[0]}")" && env -u VIRTUAL_ENV uv run --quiet python - <<'PY'
import google.auth
creds, project = google.auth.default()
print(f"klasa poświadczeń: {type(creds).__module__}.{type(creds).__name__}")
print(f"projekt z ADC:     {project}")
print(f"quota project:     {getattr(creds, 'quota_project_id', None)}")
PY
)

# --- 5. Metadane tokenu (bez samego tokenu) ----------------------------------------------
# Token przekazujemy w treści żądania POST, a nie w URL (nie trafi do historii ani logów proxy),
# i tylko do oficjalnego endpointu Google. Wypisujemy wybrane pola odpowiedzi.
step "5. Metadane tokenu dostępu z ADC"
TOKEN="$(gcloud auth application-default print-access-token)"
curl -s --fail https://oauth2.googleapis.com/tokeninfo \
  --data-urlencode "access_token=${TOKEN}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print({k: d.get(k) for k in ("email","expires_in","scope")})'
unset TOKEN

# --- 6. Impersonacja także dla gcloud (opcjonalnie) --------------------------------------
if $IMPERSONATE; then
  step "6. gcloud też działa jako konto serwisowe"
  gcloud config set auth/impersonate_service_account "$SA_EMAIL"
  echo "Wyłączenie: gcloud config unset auth/impersonate_service_account"
fi

step "Gotowe"
gcloud config configurations list
