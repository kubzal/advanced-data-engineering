#!/usr/bin/env bash
# exercise/starter/scripts/check.sh
#
# Automatycznie sprawdza część kryteriów akceptacji zadania modułu 00.
# Na starcie (przed wykonaniem zadania) sprawdzenia NIE przechodzą.
#
# Użycie:
#   export PROJECT_ID=ade-jkowalski-2611 BILLING_ACCOUNT=0X0X0X-0X0X0X-0X0X0X
#   export BUCKET=ade-jkowalski-2611-novacart-raw        # opcjonalnie; domyślnie <PROJECT_ID>-novacart-raw
#   ./scripts/check.sh
set -uo pipefail

: "${PROJECT_ID:?Ustaw PROJECT_ID}"
: "${BILLING_ACCOUNT:?Ustaw BILLING_ACCOUNT}"
BUCKET="${BUCKET:-${PROJECT_ID}-novacart-raw}"
DATASET="${DATASET:-novacart_raw}"
DATA_PREFIX="${DATA_PREFIX:-novacart/s}"
REGION="${REGION:-europe-central2}"

passed=0; failed=0
ok()   { printf '  \033[32m✔\033[0m %s\n' "$1"; passed=$((passed + 1)); }
fail() { printf '  \033[31m✘\033[0m %s\n' "$1"; failed=$((failed + 1)); }
check() { local desc=$1; shift; if "$@" >/dev/null 2>&1; then ok "$desc"; else fail "$desc"; fi; }

# Zapytanie zwracające jedną wartość. Bezpiecznik: 1 GB, etykiety modułu.
bq_value() {
  bq --project_id="$PROJECT_ID" query --use_legacy_sql=false --format=csv --quiet \
     --maximum_bytes_billed=1000000000 --label=course:ade --label=module:00 "$1" 2>/dev/null | tail -n 1
}
expect() { local desc=$1 sql=$2 expected=$3 got; got="$(bq_value "$sql")"
  if [[ "$got" == "$expected" ]]; then ok "$desc = $expected"; else fail "$desc: oczekiwano $expected, jest '${got}'"; fi; }

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' 2>/dev/null)"

echo "1. Budżet i alerty"
budgets="$(gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --format=json 2>/dev/null || echo '[]')"
check "budżet obejmuje projekt ${PROJECT_ID}, ma ≥ 3 progi, wyklucza kredyty i ma kanał e-mail" \
  python3 - "$budgets" "projects/${PROJECT_NUMBER}" <<'PY'
import json, sys
budgets, project = json.loads(sys.argv[1]), sys.argv[2]
for b in budgets:
    f = b.get("budgetFilter", {})
    if project in f.get("projects", []) \
       and len(b.get("thresholdRules", [])) >= 3 \
       and f.get("creditTypesTreatment") == "EXCLUDE_ALL_CREDITS" \
       and b.get("notificationsRule", {}).get("monitoringNotificationChannels"):
        sys.exit(0)
sys.exit(1)
PY

echo "2. Cloud Storage"
bucket_json="$(gcloud storage buckets describe "gs://${BUCKET}" --format=json 2>/dev/null || echo '{}')"
check "bucket gs://${BUCKET} istnieje w ${REGION} z etykietami course=ade, module=00" \
  python3 -c 'import json,sys; b=json.loads(sys.argv[1]); l=b.get("labels") or {}; \
sys.exit(0 if b.get("location","").lower()==sys.argv[2] and l.get("course")=="ade" and l.get("module")=="00" else 1)' \
  "$bucket_json" "$REGION"
orders_files="$(gcloud storage ls "gs://${BUCKET}/${DATA_PREFIX}/orders/" 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$orders_files" == "61" ]]; then ok "61 partycji dt=… z zamówieniami w GCS"; else fail "partycje zamówień w GCS: oczekiwano 61, jest ${orders_files}"; fi

echo "3. BigQuery"
check "tabela ${DATASET}.orders jest tabelą zewnętrzną z partycjonowaniem hive" \
  bash -c "bq --project_id='$PROJECT_ID' show --format=json '${DATASET}.orders' | python3 -c 'import json,sys; t=json.load(sys.stdin); sys.exit(0 if t[\"type\"]==\"EXTERNAL\" and \"hivePartitioningOptions\" in t[\"externalDataConfiguration\"] else 1)'"
check "zapytanie bez filtra partycji jest odrzucane (require_partition_filter)" \
  bash -c "! bq --project_id='$PROJECT_ID' query --use_legacy_sql=false --dry_run 'SELECT COUNT(*) FROM ${DATASET}.orders'"

W="WHERE dt BETWEEN DATE '2025-11-01' AND DATE '2025-12-31'"
expect "liczba zamówień"            "SELECT COUNT(*) FROM ${DATASET}.orders $W"            "24506"
expect "liczba partycji (dni)"      "SELECT COUNT(DISTINCT dt) FROM ${DATASET}.orders $W"  "61"
expect "zamówienia w Black Friday"  "SELECT COUNT(*) FROM ${DATASET}.orders WHERE dt = DATE '2025-11-28'" "1046"
expect "zamówienia dostarczone"     "SELECT COUNTIF(status = 'delivered') FROM ${DATASET}.orders $W" "20865"
expect "przychód PLN"               "SELECT CAST(SUM(total_amount) AS STRING) FROM ${DATASET}.orders $W AND currency = 'PLN'" "12681259.98"
expect "liczba klientów"            "SELECT COUNT(*) FROM ${DATASET}.customers"            "20000"

echo "4. Koszty"
jobs="$(bq_value "SELECT COUNT(*) FROM \`region-${REGION}\`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
  WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    AND EXISTS (SELECT 1 FROM UNNEST(labels) l WHERE l.key = 'module' AND l.value = '00')")"
if [[ "${jobs:-0}" =~ ^[0-9]+$ ]] && (( jobs > 0 )); then ok "zadania BigQuery z etykietą module=00: ${jobs}"; else fail "brak zadań z etykietą module=00 w INFORMATION_SCHEMA.JOBS"; fi

echo
echo "Wynik: ${passed} OK, ${failed} do poprawy."
echo "Ręcznie sprawdź jeszcze: limity BigQuery w konsoli (Quotas & System Limits) i raport kosztów w README."
(( failed == 0 ))
