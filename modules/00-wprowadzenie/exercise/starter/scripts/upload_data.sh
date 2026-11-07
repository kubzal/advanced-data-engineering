#!/usr/bin/env bash
# exercise/starter/scripts/upload_data.sh
#
# Generuje dane NovaCart (skala S, seed 42) i wgrywa je do Cloud Storage.
#
# Użycie:
#   DATA_URI=gs://ade-jkowalski-2611-novacart-raw/novacart/s ./scripts/upload_data.sh
#   (DATA_URI wypisuje: terraform -chdir=terraform/data output -raw data_uri)
set -euo pipefail

: "${DATA_URI:?Ustaw DATA_URI, np. gs://<bucket>/novacart/s}"
REPO="$(cd "$(dirname "$0")/../../../../.." && pwd)"
LOCAL_DIR="${LOCAL_DIR:-${REPO}/data/exercise-00}"

if [[ -f "${LOCAL_DIR}/_SUCCESS" ]]; then
  echo "Dane już wygenerowane w ${LOCAL_DIR}, pomijam generowanie."
else
  (cd "${REPO}/datasets" && uv run novacart generate --scale s --seed 42 -o "${LOCAL_DIR}")
fi

echo "Wgrywam ${LOCAL_DIR} -> ${DATA_URI}"
# rsync wysyła tylko brakujące lub zmienione pliki, więc ponowne uruchomienie jest tanie.
gcloud storage rsync --recursive "${LOCAL_DIR}" "${DATA_URI}"

echo "Liczba plików w ${DATA_URI}:"
gcloud storage ls --recursive "${DATA_URI}/**" | wc -l
