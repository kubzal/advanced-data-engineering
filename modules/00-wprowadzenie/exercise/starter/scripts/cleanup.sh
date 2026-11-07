#!/usr/bin/env bash
# exercise/starter/scripts/cleanup.sh
#
# Usuwa zasoby DANYCH zadania (bucket, zbiór BigQuery, tabele) i lokalną kopię danych.
# Bezpieczniki (budżet, limity) zostają: mają chronić projekt przez cały kurs.
#
# Użycie (z katalogu z terraform/data, czyli exercise/starter albo exercise/solution):
#   ./scripts/cleanup.sh            albo   ../starter/scripts/cleanup.sh
set -euo pipefail

TF_DIR="${TF_DIR:-terraform/data}"
REPO="$(cd "$(dirname "$0")/../../../../.." && pwd)"

terraform -chdir="$TF_DIR" destroy

read -r -p "Usunąć także lokalne dane ${REPO}/data/exercise-00? [t/N] " answer
if [[ "$answer" == "t" ]]; then
  rm -rf "${REPO}/data/exercise-00"
  echo "Usunięto."
fi

echo "Sprawdź po ~24 h w Billing → Reports (filtr: etykieta module=00), czy koszty przestały rosnąć."
