# Kod startowy — Bezpieczny projekt i pierwsze dane NovaCart w chmurze

Kod startowy oszczędza Ci pracy niezwiązanej z celem zadania: konfiguracji providerów, zmiennych, generowania i wgrywania danych oraz automatycznego sprawdzania wyników. Istota zadania, czyli bezpieczniki, bucket, tabele zewnętrzne i zapytania, jest do uzupełnienia w miejscach oznaczonych `TODO(zadanie):`.

## Zawartość

| Plik | Opis | Do uzupełnienia? |
|---|---|---|
| `terraform/guardrails/versions.tf`, `variables.tf` | providery `google` i `google-beta`, etykiety, zmienne | nie |
| `terraform/guardrails/main.tf` | API, kanał e-mail, temat Pub/Sub, szkielet budżetu | **tak**: filtr budżetu, progi, powiadomienia, limity BigQuery |
| `terraform/guardrails/outputs.tf` | outputy | tak: wartości limitów |
| `terraform/data/versions.tf`, `variables.tf`, `outputs.tf` | provider, zmienne (w tym `create_tables`), outputy | nie |
| `terraform/data/main.tf` | szkielet bucketu, zbioru i tabeli `orders` | **tak**: lokalizacje, ustawienia bucketu, partycjonowanie hive, tabela `customers` |
| `terraform/*/terraform.tfvars.example` | przykładowe wartości zmiennych | skopiuj do `terraform.tfvars` |
| `sql/control_queries.sql` | opis zapytań Q1–Q5 | **tak** |
| `sql/cost_report.sql` | opis raportu kosztów | **tak** |
| `scripts/upload_data.sh` | generuje dane (S, seed 42) i wgrywa je do GCS (`gcloud storage rsync`) | nie |
| `scripts/check.sh` | sprawdza automatycznie większość kryteriów akceptacji | nie |
| `scripts/cleanup.sh` | `terraform destroy` dla danych + opcjonalnie usunięcie lokalnej kopii | nie |
| `REPORT.md` | Twój raport (utwórz według szablonu z treści zadania) | **tak** |

## Uruchomienie

Wymagania: projekt z lekcji [00.02](../../02-konto-i-projekt-gcp.md), zalogowane `gcloud` i ADC (lekcja [00.04](../../04-narzedzia-lokalne.md)), Terraform ≥ 1.9, `uv`.

```bash
cd modules/00-wprowadzenie/exercise/starter
export PROJECT_ID=ade-jkowalski-2611 BILLING_ACCOUNT=0X0X0X-0X0X0X-0X0X0X

# 0. Stan wyjściowy: sprawdzenia NIE przechodzą
./scripts/check.sh

# 1. Bezpieczniki
cp terraform/guardrails/terraform.tfvars.example terraform/guardrails/terraform.tfvars   # uzupełnij
terraform -chdir=terraform/guardrails init
terraform -chdir=terraform/guardrails apply

# 2. Miejsce na dane (bez tabel), 3. dane, 4. tabele
cp terraform/data/terraform.tfvars.example terraform/data/terraform.tfvars               # uzupełnij
terraform -chdir=terraform/data init
terraform -chdir=terraform/data apply
DATA_URI="$(terraform -chdir=terraform/data output -raw data_uri)" ./scripts/upload_data.sh
terraform -chdir=terraform/data apply -var create_tables=true

# 5. Zapytania kontrolne i sprawdzenie
bq query --project_id="$PROJECT_ID" --use_legacy_sql=false \
  --maximum_bytes_billed=1000000000 --label=course:ade --label=module:00 < sql/control_queries.sql
./scripts/check.sh
```

Pliki `terraform.tfvars` są w `.gitignore`, więc adres e-mail i ID konta rozliczeniowego nie trafią do repozytorium.

Skrypty `check.sh` w stanie początkowym **nie przechodzą**. Zadanie jest ukończone, gdy `check.sh` kończy się wynikiem `0 do poprawy`, a pozostałe kryteria akceptacji z [treści zadania](../README.md#kryteria-akceptacji) (limity w konsoli, `No changes` w planie, raport kosztów) są spełnione.

> [!NOTE]
> `check.sh` sam wykonuje kilka małych zapytań, z `maximum_bytes_billed` i etykietami modułu. Pojawią się więc w `INFORMATION_SCHEMA.JOBS` i w Twoim raporcie kosztów. To zamierzone: zobaczysz, ile kosztuje automatyczna weryfikacja.
