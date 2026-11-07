# Moduł 00 — przykłady kodu

## Przygotowanie

```bash
# z katalogu głównego repozytorium
cd datasets && uv sync && uv run novacart generate --scale s -o ../data/s && cd ..

cd modules/00-wprowadzenie
bash examples/check_env.sh                 # czy masz wszystkie narzędzia

cd examples
uv sync                                    # duckdb, google-cloud-bigquery, google-cloud-pubsub
export GOOGLE_CLOUD_PROJECT=twoj-projekt   # tylko dla przykładów wymagających chmury
```

Skrypty `*.sh` uruchamiasz z katalogu modułu (`bash examples/…`), a przykłady w Pythonie z katalogu `examples/` (`uv run python …`). Dokładne polecenia i wyniki są w lekcjach.

## Przykłady

| Plik | Lekcja | Co pokazuje | Wymaga chmury | Szacowany koszt |
|---|---|---|---|---|
| `check_env.sh` | [00.04](../04-narzedzia-lokalne.md#5--w-praktyce) | Sprawdza wersje narzędzi kursu i zgłasza brakujące; niczego nie instaluje | nie | 0 |
| `01_bootstrap_project.sh` | [00.02](../02-konto-i-projekt-gcp.md#5--w-praktyce) | Idempotentne utworzenie projektu z etykietami, podpięcie billingu, włączenie API | tak | 0 (samo utworzenie projektu) |
| `02_adc_setup.sh` | [00.04](../04-narzedzia-lokalne.md#5--w-praktyce) | Osobna konfiguracja `gcloud`, ADC, *quota project*, impersonacja konta serwisowego bez kluczy | tak | 0 |
| `03_first_query_dry_run.sh` | [00.03](../03-bezpieczenstwo-kosztowe.md#5--w-praktyce) | `bq query --dry_run` i `--maximum_bytes_billed` na zbiorze publicznym | tak (BigQuery) | 0 (*dry run*); przy uruchomieniu w Free Tier |
| `03_dry_run.py` | [00.03](../03-bezpieczenstwo-kosztowe.md#5--w-praktyce) | To samo z biblioteki `google-cloud-bigquery`: szacunek kosztu i blokada zapytania | tak (BigQuery) | jw. |
| `terraform/budget/` | [00.03](../03-bezpieczenstwo-kosztowe.md#5--w-praktyce) | Budżet z progami i prognozą, kanał e-mail, temat Pub/Sub, dzienne *custom quotas* BigQuery | tak | 0 |
| `99_cleanup.sh` | [00.03](../03-bezpieczenstwo-kosztowe.md#5--w-praktyce) | Sprzątanie zasobów po etykietach albo usunięcie całego projektu (z potwierdzeniem) | tak | 0 |
| `compose/docker-compose.yml` | [00.05](../05-emulatory-i-praca-offline.md#5--w-praktyce) | Emulator Pub/Sub, Kafka (KRaft), PostgreSQL z `wal_level=logical`, fake-gcs-server, emulatory Spanner i Bigtable (profile) | nie (Docker) | 0 |
| `05_pubsub_emulator_demo.py` | [00.05](../05-emulatory-i-praca-offline.md#5--w-praktyce) | Temat, subskrypcje (także z filtrem), publikacja zdarzeń NovaCart i odbiór w emulatorze | nie (emulator) | 0 |
| `06_duckdb_local_warehouse.py` | [00.05](../05-emulatory-i-praca-offline.md#5--w-praktyce) | DuckDB jako lokalna hurtownia: przychód, lejek, duplikaty, skośność, *partition pruning* | nie | 0 |
| `07_generate_and_inspect.sh` | [00.07](../07-generator-danych-novacart.md#5--w-praktyce) | Generowanie danych, manifest, liczności, anomalie, odcisk palca plików (determinizm) | nie | 0 |

## Sprzątanie

```bash
# zasoby chmurowe z przykładów (etykieta module=00); skrypt domyślnie tylko pokazuje, co usunie
bash examples/99_cleanup.sh labels 00

# budżet i limity z Terraform
terraform -chdir=examples/terraform/budget destroy

# lokalne kontenery i wolumeny
docker compose -f examples/compose/docker-compose.yml --profile all down -v
```

> [!CAUTION]
> Uruchom sprzątanie po zakończeniu modułu. **Nie usuwaj** budżetu i limitów, jeśli używasz tego samego projektu w kolejnych modułach: to Twoje bezpieczniki na cały kurs. Zasoby z etykietą `module=00` znajdziesz poleceniem
> `gcloud asset search-all-resources --scope=projects/$GOOGLE_CLOUD_PROJECT --query="labels.module=00"`.
