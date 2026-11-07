# 🧪 Zadanie końcowe — Bezpieczny projekt i pierwsze dane NovaCart w chmurze

| | |
|---|---|
| **Moduł** | [00 — Wprowadzenie, środowisko i bezpieczne korzystanie z chmury](../README.md) |
| **Szacowany czas** | 1,5–2 h (+ krótki powrót po ~24 h, żeby odczytać koszty w Billing Reports) |
| **Szacowany koszt** | ~0 USD: zapytania mieszczą się w Free Tier BigQuery; storage ~124 MB przez kilka dni i ~450 operacji zapisu to ułamki centa według cen katalogowych |
| **Sprawdzane cele modułu** | 1, 2, 3, 7: konfiguracja bezpieczników kosztowych (budżet, alerty, custom quotas), praca z `gcloud`, `bq` i Terraform, uruchomienie generatora NovaCart, tabele zewnętrzne z partycjonowaniem hive, pomiar i dokumentowanie kosztów |

## Kontekst biznesowy

Jesteś nowym data engineerem w zespole platformy danych NovaCart. Tydzień temu jedno zapytanie cykliczne bez filtra partycji przetworzyło w weekend kilkadziesiąt TiB i wygenerowało rachunek na ponad 600 USD (lekcja [00.03](../03-bezpieczenstwo-kosztowe.md)). Budżet z alertem istniał, ale niczego nie zatrzymał.

Szefowa zespołu wprowadza zasadę: **żaden nowy projekt nie dostaje danych, dopóki nie ma bezpieczników kosztowych**. Twoje zadanie to przygotować wzorcowy projekt, który zespół będzie kopiował. Projekt ma mieć bezpieczniki, dane surowe w Cloud Storage dostępne w BigQuery bez kopiowania i raport, ile to wszystko kosztowało. Dział finansów chce zobaczyć liczby, a nie zapewnienia.

## Cel

Skonfiguruj projekt GCP z budżetem, alertem e-mail i dziennymi limitami zapytań BigQuery. Wgraj dane NovaCart (skala S) do bucketu w UE, udostępnij je w BigQuery jako tabele zewnętrzne z partycjonowaniem hive, wykonaj zapytania kontrolne i udokumentuj koszt każdej operacji.

## Dane wejściowe

```bash
cd datasets
uv run novacart generate --scale s --seed 42 -o ../data/exercise-00
```

Polecenie wykonuje też skrypt `starter/scripts/upload_data.sh`. Wygenerowane zostaną domyślne komponenty (`entities`, `orders`, `clickstream`, `partners`), łącznie ~124 MB w ~430 plikach. W zadaniu wykorzystasz:

| Katalog | Zawartość | Uwagi |
|---|---|---|
| `orders/dt=RRRR-MM-DD/part-00000.parquet` | zamówienia, 61 partycji dziennych (1.11–31.12.2025) | układ katalogów w stylu *hive*: nazwa katalogu to `kolumna=wartość` |
| `customers/part-00000.parquet` | klienci (stan na koniec okresu) | zawiera fikcyjne dane osobowe |
| `_manifest.json` | parametry generatora i liczności tabel | punkt odniesienia dla Twoich wyników |

Kwoty są w trzech walutach (PLN, EUR, CZK). To ma znaczenie przy sumowaniu.

## Wymagania

### Funkcjonalne

1. **Bezpieczniki** (Terraform, katalog `terraform/guardrails`):
   - budżet miesięczny obejmujący **tylko** Twój projekt, wykluczający kredyty, z co najmniej trzema progami wydatków faktycznych i jednym progiem prognozy;
   - powiadomienia na Twój adres e-mail (kanał Cloud Monitoring) i do tematu Pub/Sub;
   - custom quota `QueryUsagePerDay` = **1 TiB/dzień** oraz `QueryUsagePerUserPerDay` = **0,5 TiB/dzień**.
2. **Miejsce na dane** (Terraform, katalog `terraform/data`):
   - bucket w `europe-central2` z etykietami `course=ade`, `module=00`, jednolitym dostępem na poziomie bucketu, blokadą dostępu publicznego i wyłączonym *soft delete*;
   - zbiór BigQuery `novacart_raw` w tej samej lokalizacji.
3. **Dane:** wygenerowane z parametrami z sekcji „Dane wejściowe” i wgrane do `gs://<bucket>/novacart/s/`.
4. **Tabele zewnętrzne:**
   - `novacart_raw.orders` na plikach Parquet z partycjonowaniem hive po `dt` i **wymaganym filtrem partycji**;
   - `novacart_raw.customers`.
5. **Zapytania kontrolne** (`sql/control_queries.sql`): Q1–Q5 opisane w pliku, uruchomione z `maximum_bytes_billed` ≤ 1 GB i etykietami `course=ade`, `module=00`.
6. **Raport kosztów** (`sql/cost_report.sql` + `REPORT.md`): koszt każdej kategorii operacji (zapytania, storage, operacje na obiektach) według cen katalogowych i po uwzględnieniu Free Tier/kredytów, z dwóch źródeł: `INFORMATION_SCHEMA.JOBS` i *Billing → Reports*.

### Niefunkcjonalne

- **Koszt:** każde zapytanie ma `maximum_bytes_billed` ≤ 1 GB; budżet nie przekracza 20 jednostek waluty konta miesięcznie.
- **Idempotencja:** ponowne `terraform apply` nie wprowadza zmian, a ponowne `upload_data.sh` niczego nie wgrywa drugi raz.
- **Bezpieczeństwo:** bez kluczy kont serwisowych (uwierzytelnianie przez ADC), bez publicznego dostępu do bucketu.
- **Cykl życia:** bezpieczniki i dane mają **osobne stany** Terraform. Dane usuwasz po zadaniu jednym poleceniem, a bezpieczniki zostają na cały kurs.
- Cała infrastruktura w Terraform (poza wgraniem danych skryptem).

## Kryteria akceptacji

- [ ] `scripts/check.sh` kończy się wynikiem `0 do poprawy`
- [ ] Budżet obejmuje tylko Twój projekt (filtr po **numerze** projektu), ma `EXCLUDE_ALL_CREDITS`, ≥ 3 progi faktyczne i próg prognozy
- [ ] W konsoli *IAM & Admin → Quotas & System Limits* limit *Query usage per day* wynosi 1 TiB, a *Query usage per day per user* 0,5 TiB (zrzut ekranu w raporcie)
- [ ] Bucket jest w `europe-central2`, ma etykiety `course=ade`, `module=00`, *soft delete* wyłączony i zawiera 61 partycji `orders/dt=…`
- [ ] `SELECT COUNT(*) FROM novacart_raw.orders` **bez** filtra `dt` jest odrzucane
- [ ] Q1: **24 506** zamówień, **61** partycji, zakres **2025-11-01 … 2025-12-31**
- [ ] Q2: **20 865** zamówień w statusie `delivered`
- [ ] Q3: przychód w PLN = **12 681 259,98**, w EUR = **2 984 871,97**, w CZK = **20 245 410,80**
- [ ] Q4: w Black Friday **1 046** zamówień (CZK 128, EUR 430, PLN 488)
- [ ] Q5: **20 000** klientów, w tym **78** zanonimizowanych po wniosku RODO
- [ ] Ponowne `terraform plan` w obu katalogach pokazuje `No changes`
- [ ] Raport zawiera tabelę kosztów z `INFORMATION_SCHEMA.JOBS` (bajty przetworzone i rozliczone dla każdego zapytania) oraz z *Billing → Reports* (filtr: projekt, etykieta `module=00`)
- [ ] `scripts/cleanup.sh` usuwa bucket i zbiór, a budżet i limity zostają

## Rezultaty do oddania

Pracujesz bezpośrednio w katalogu `starter/` (najlepiej na własnej gałęzi lub w forku repozytorium):

```text
exercise/starter/
├── REPORT.md                 # Twój raport (szablon poniżej)
├── terraform/
│   ├── guardrails/           # budżet, kanał e-mail, temat Pub/Sub, limity BigQuery
│   └── data/                 # bucket, zbiór, tabele zewnętrzne
├── sql/
│   ├── control_queries.sql   # Q1–Q5
│   └── cost_report.sql       # koszty z INFORMATION_SCHEMA.JOBS
└── scripts/                  # upload_data.sh, check.sh, cleanup.sh
```

**Szablon raportu** (w pliku `REPORT.md`):

1. **Podsumowanie** (3–5 zdań): co powstało, ile kosztowało, czy kryteria są spełnione.
2. **Architektura:** diagram (Mermaid) z podziałem na bezpieczniki i dane oraz przepływem danych: generator → GCS → BigQuery.
3. **Kluczowe decyzje i odrzucone alternatywy:** np. region, tabela zewnętrzna czy natywna, jeden czy dwa stany Terraform, wartości progów i limitów.
4. **Pomiary:** wyniki Q1–Q5, bajty przetworzone i rozliczone dla każdego zapytania, tabela kosztów (cena katalogowa i po Free Tier/kredytach). Wyjaśnij, skąd się wzięło minimum 10 MiB.
5. **Ograniczenia i co dalej:** czego bezpieczniki **nie** chronią? Co zrobił(a)byś w projekcie zespołowym?

## Podpowiedzi

<details>
<summary>Podpowiedź 1 — kierunek</summary>

Zastanów się nad **kolejnością**. Tabela zewnętrzna na plikach Parquet odczytuje schemat z plików w momencie tworzenia, więc pliki muszą już leżeć w buckecie. Bucket musi jednak istnieć, zanim cokolwiek do niego wgrasz. Do tego bezpieczniki i dane mają różny cykl życia: dane usuwasz po zadaniu, bezpieczniki zostają. Gdzie przebiegają granice między etapami i stanami Terraform?

</details>

<details>
<summary>Podpowiedź 2 — narzędzia</summary>

- Zasoby Terraform: `google_billing_budget` (filtr `projects = ["projects/<NUMER>"]`, `credit_types_treatment`, `threshold_rules`, `all_updates_rule`), `google_service_usage_consumer_quota_override` (provider `google-beta`), `google_storage_bucket` (`soft_delete_policy`), `google_bigquery_table` z blokiem `external_data_configuration` → `hive_partitioning_options`.
- Numer projektu: `data "google_project"` → atrybut `number`.
- Wgrywanie: `gcloud storage rsync --recursive` (wysyła tylko brakujące pliki).
- Koszty zapytań: `` `region-europe-central2`.INFORMATION_SCHEMA.JOBS_BY_PROJECT `` (kolumny `total_bytes_processed`, `total_bytes_billed`, `labels`).
- Koszty wszystkiego: *Billing → Reports*, filtr na projekt i etykietę, grupowanie po SKU. Dane pojawiają się z opóźnieniem do ~24 h.

</details>

<details>
<summary>Podpowiedź 3 — prawie rozwiązanie</summary>

Dwa katalogi Terraform z osobnymi stanami: `guardrails` (API, kanał, temat, budżet, limity) i `data` (bucket, zbiór, tabele). W `data` tabele zależą od zmiennej `create_tables` (`count = var.create_tables ? 1 : 0`). Kolejność:

1. `terraform -chdir=terraform/guardrails apply`
2. `terraform -chdir=terraform/data apply` (z `create_tables = false`)
3. `DATA_URI=$(terraform -chdir=terraform/data output -raw data_uri) ./scripts/upload_data.sh`
4. `terraform -chdir=terraform/data apply -var create_tables=true`
5. `bq query … < sql/control_queries.sql`, potem `./scripts/check.sh`

Tabela `orders`: `source_uris = ["gs://…/novacart/s/orders/*"]`, `hive_partitioning_options { mode = "AUTO", source_uri_prefix = "gs://…/novacart/s/orders/", require_partition_filter = true }`. Limity: `override_value` w MiB (1 TiB = 1 048 576).

</details>

## Ocena

| Kryterium | Waga | Co oznacza „bardzo dobrze” |
|---|---|---|
| Poprawność | 30% | Wszystkie kryteria akceptacji spełnione; `check.sh` bez błędów; wyniki Q1–Q5 zgodne |
| Jakość decyzji | 25% | Uzasadnione: region, osobne stany, progi i limity, tabela zewnętrzna; nazwane alternatywy |
| Wydajność i koszt | 20% | Każde zapytanie z limitem bajtów; zapytania czytają tylko potrzebne partycje i kolumny; koszt policzony z dwóch źródeł |
| Jakość kodu i IaC | 15% | Terraform sformatowany (`terraform fmt`), zmienne opisane, etykiety na zasobach, brak kluczy |
| Raport | 10% | Zwięzły, z diagramem, tabelą kosztów i listą ograniczeń bezpieczników |

## Rozszerzenia (dla ambitnych)

- **Bezpiecznik w akcji:** dodaj funkcję (Cloud Run functions), która czyta wiadomości z tematu budżetu i loguje decyzję „wyłączyłbym billing” (tryb symulacji jak w dokumentacji Google). Opisz, dlaczego nie włączasz trybu rzeczywistego.
- **Schemat jako kontrakt:** zamiast `autodetect` użyj schematów z `uv run novacart schemas --format bigquery` (mają opisy kolumn). Porównaj, co się zmienia w tabeli i w kolejności tworzenia zasobów.
- **Clickstream i duplikaty:** utwórz tabelę zewnętrzną `clickstream` i policz zdarzenia oraz unikalne `event_id` (oczekiwane: 1 946 266 i 1 926 628). Skąd różnica? (zajrzyj do [dokumentacji generatora](../../../datasets/README.md)).
- **Zewnętrzna czy natywna:** załaduj `orders` do tabeli natywnej (`bq load`) i porównaj `total_bytes_billed` tych samych zapytań na obu tabelach.
- **Inna platforma:** w trialu Snowflake ustaw *resource monitor* z akcją `SUSPEND` na warehouse i porównaj z bezpiecznikami GCP.

## Sprzątanie

```bash
./scripts/cleanup.sh        # terraform destroy w terraform/data + opcjonalnie lokalne dane
```

Bezpieczniki z `terraform/guardrails` **zostaw**: będą chronić projekt w kolejnych modułach. Usuniesz je dopiero po kursie (`terraform -chdir=terraform/guardrails destroy` albo usunięcie całego projektu).

> [!CAUTION]
> Nie zostawiaj działających zasobów po zakończeniu zadania. Sprawdź w *Billing → Reports*, czy koszty projektu przestały rosnąć. Dane billingowe spływają z opóźnieniem, więc zajrzyj tam ponownie następnego dnia.

---

<sub>Kod startowy: [starter/](starter/README.md). Rozwiązanie wzorcowe: [solution/](solution/README.md); zajrzyj tam dopiero po samodzielnej próbie.</sub>
