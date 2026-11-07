#!/usr/bin/env bash
# examples/03_first_query_dry_run.sh
#
# Pierwsze zapytania w BigQuery z bezpiecznikami:
#   1) --dry_run       szacuje liczbę przetworzonych bajtów, nic nie kosztuje i niczego nie uruchamia,
#   2) --maximum_bytes_billed  zatrzymuje zapytanie PRZED wykonaniem, jeśli szacunek przekracza limit.
#
# Zapytania dotyczą publicznego zbioru bigquery-public-data.samples (lokalizacja US).
# Opłata (jeśli jakakolwiek) trafia do projektu PROJECT_ID, nie do właściciela danych.
#
# Użycie:  PROJECT_ID=moj-projekt ./03_first_query_dry_run.sh
set -euo pipefail

: "${PROJECT_ID:?Ustaw PROJECT_ID}"
LIMIT_BYTES="${LIMIT_BYTES:-1000000000}"  # 1 GB: górna granica dla zapytań w tym skrypcie
PRICE_PER_TIB_USD="6.25"                  # cena katalogowa on-demand (US/EU); sprawdź aktualny cennik

bq_q() { bq --project_id="$PROJECT_ID" query --use_legacy_sql=false --nouse_cache "$@"; }

# Zwraca liczbę bajtów, które przetworzyłoby zapytanie (dry run).
estimate_bytes() {
  bq_q --dry_run "$1" 2>&1 | grep -oE '[0-9]+ bytes' | grep -oE '[0-9]+'
}

report() {
  local label=$1 sql=$2 bytes
  bytes="$(estimate_bytes "$sql")"
  awk -v l="$label" -v b="$bytes" -v p="$PRICE_PER_TIB_USD" 'BEGIN {
    gib = b / 2^30; usd = b / 2^40 * p
    printf "%-38s %16d B  %9.2f GiB  ~%.4f USD\n", l, b, gib, usd }'
}

echo "== Szacunki (dry run, koszt 0) =="
report "SELECT * (cała tabela)" \
  'SELECT * FROM `bigquery-public-data.samples.wikipedia`'
report "SELECT * ... LIMIT 10" \
  'SELECT * FROM `bigquery-public-data.samples.wikipedia` LIMIT 10'
report "SELECT title (jedna kolumna)" \
  'SELECT title FROM `bigquery-public-data.samples.wikipedia`'
report "SELECT COUNT(*) (tylko metadane)" \
  'SELECT COUNT(*) FROM `bigquery-public-data.samples.wikipedia`'
report "Mała tabela: shakespeare" \
  'SELECT corpus, SUM(word_count) AS words FROM `bigquery-public-data.samples.shakespeare` GROUP BY corpus'

echo
echo "== Zapytanie z bezpiecznikiem: SELECT * LIMIT 10, limit ${LIMIT_BYTES} B =="
# Oczekiwany wynik: błąd „Query exceeded limit for bytes billed”, zapytanie nie rusza i nic nie kosztuje.
if bq_q --maximum_bytes_billed="$LIMIT_BYTES" \
     'SELECT * FROM `bigquery-public-data.samples.wikipedia` LIMIT 10' >/dev/null 2>err.log; then
  echo "Zapytanie wykonane (nieoczekiwane: sprawdź LIMIT_BYTES)"
else
  echo "Zatrzymane przed wykonaniem:"; sed 's/^/  /' err.log
fi
rm -f err.log

echo
echo "== Tanie zapytanie z tym samym bezpiecznikiem =="
bq_q --maximum_bytes_billed="$LIMIT_BYTES" \
  'SELECT corpus, SUM(word_count) AS words
   FROM `bigquery-public-data.samples.shakespeare`
   GROUP BY corpus ORDER BY words DESC LIMIT 5'
