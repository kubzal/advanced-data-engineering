#!/usr/bin/env bash
# examples/99_cleanup.sh
#
# Sprząta zasoby kursu. Dwa tryby:
#
#   ./99_cleanup.sh labels [MODULE]   usuwa zasoby z etykietą course=ade (i opcjonalnie module=MODULE)
#                                     w projekcie PROJECT_ID: buckety, zbiory BigQuery, tematy
#                                     i subskrypcje Pub/Sub, maszyny Compute Engine, klastry Dataproc
#   ./99_cleanup.sh project           usuwa CAŁY projekt PROJECT_ID (30 dni na przywrócenie)
#
# Domyślnie działa na sucho (DRY_RUN=1): tylko wypisuje, co zostałoby usunięte.
# Faktyczne usuwanie: DRY_RUN=0 ./99_cleanup.sh labels 00
#
# Zasoby zarządzane przez Terraform usuwaj przez `terraform destroy`. Ten skrypt to
# siatka bezpieczeństwa na rzeczy utworzone ręcznie albo „osierocone”.
set -euo pipefail

: "${PROJECT_ID:?Ustaw PROJECT_ID}"
MODE="${1:-}"
MODULE="${2:-}"
DRY_RUN="${DRY_RUN:-1}"
REGION="${REGION:-europe-central2}"

filter="labels.course=ade"
bq_filter="labels.course:ade"
if [[ -n "$MODULE" ]]; then
  filter+=" AND labels.module=${MODULE}"
  bq_filter+=" labels.module:${MODULE}"
fi

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    printf '[usuwam]  %s\n' "$*"
    "$@"
  fi
}

confirm() {
  local expected=$1 answer
  read -r -p "Wpisz '${expected}', aby potwierdzić: " answer
  [[ "$answer" == "$expected" ]] || { echo "Przerwano."; exit 1; }
}

cleanup_by_labels() {
  echo "Projekt: ${PROJECT_ID}   filtr: ${filter}   DRY_RUN=${DRY_RUN}"
  [[ "$DRY_RUN" == "1" ]] || confirm "$PROJECT_ID"

  # Cloud Storage: buckety razem z zawartością.
  for b in $(gcloud storage buckets list --project="$PROJECT_ID" \
               --filter="$filter" --format='value(name)'); do
    run gcloud storage rm --recursive "gs://${b}"
  done

  # BigQuery: zbiory danych razem z tabelami (bq używa innej składni filtra).
  for d in $(bq ls --project_id="$PROJECT_ID" --filter="$bq_filter" --format=json \
               | python3 -c 'import json,sys; [print(x["datasetReference"]["datasetId"]) for x in json.load(sys.stdin) or []]'); do
    run bq rm -r -f -d "${PROJECT_ID}:${d}"
  done

  # Pub/Sub: najpierw subskrypcje, potem tematy.
  for s in $(gcloud pubsub subscriptions list --project="$PROJECT_ID" \
               --filter="$filter" --format='value(name)'); do
    run gcloud pubsub subscriptions delete "$s" --project="$PROJECT_ID" --quiet
  done
  for t in $(gcloud pubsub topics list --project="$PROJECT_ID" \
               --filter="$filter" --format='value(name)'); do
    run gcloud pubsub topics delete "$t" --project="$PROJECT_ID" --quiet
  done

  # Compute Engine: maszyny (płacisz za każdą sekundę działania i za dyski).
  gcloud compute instances list --project="$PROJECT_ID" --filter="$filter" \
      --format='value(name,zone.basename())' 2>/dev/null |
  while read -r name zone; do
    run gcloud compute instances delete "$name" --zone="$zone" --project="$PROJECT_ID" --quiet
  done

  # Dataproc: klastry w domyślnym regionie (najczęściej zapominany, drogi zasób).
  for c in $(gcloud dataproc clusters list --project="$PROJECT_ID" --region="$REGION" \
               --filter="$filter" --format='value(clusterName)' 2>/dev/null); do
    run gcloud dataproc clusters delete "$c" --region="$REGION" --project="$PROJECT_ID" --quiet
  done

  echo "Gotowe. Sprawdź jeszcze: Billing → Reports (filtr: projekt, etykieta course=ade)."
}

delete_project() {
  echo "Usunięcie projektu ${PROJECT_ID} zatrzymuje WSZYSTKIE zasoby i naliczanie opłat."
  echo "Projekt przechodzi w stan DELETE_REQUESTED; przez ok. 30 dni można go przywrócić:"
  echo "  gcloud projects undelete ${PROJECT_ID}"
  echo "Identyfikator projektu nie będzie już dostępny do ponownego użycia."
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] gcloud projects delete %s\n' "$PROJECT_ID"
    return
  fi
  confirm "$PROJECT_ID"
  gcloud projects delete "$PROJECT_ID" --quiet
}

case "$MODE" in
  labels)  cleanup_by_labels ;;
  project) delete_project ;;
  *) sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
