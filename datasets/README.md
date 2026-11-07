# Generator danych NovaCart

Syntetyczne, ale realistyczne dane fikcyjnego marketplace'u **NovaCart**. Działa w sześciu krajach (PL, DE, CZ, SK, LT, NL), w trzech walutach, z trzema przewoźnikami i sześcioma metodami płatności. Na tych danych opierają się przykłady i zadania w całym kursie.

Generator został zaprojektowany z myślą o nauce data engineeringu, a nie tylko o „jakichś danych”:

- **Wszystkie źródła są ze sobą spójne.** Zamówienie ma sesję w clickstreamie zakończoną zdarzeniem `purchase`, płatności w bramce, zdarzenia w plikach przewoźnika i historię zmian w CDC. Wszystko da się złączyć.
- **Dane są brudne w kontrolowany sposób.** Zawierają duplikaty, zdarzenia spóźnione i nieuporządkowane, rozjechane zegary urządzeń, uszkodzone rekordy, nieogłoszoną zmianę schematu, brakujący plik i błędne jednostki. Każdy problem jest parametryzowany i udokumentowany.
- **Wynik jest deterministyczny.** Ten sam `--seed` i te same parametry dają identyczne pliki (bajt w bajt), niezależnie od liczby procesów. Rozwiązania zadań mogą więc odwoływać się do konkretnych liczb.
- **Skaluje się od MB do setek GB.** Generator jest wektoryzowany (numpy/pyarrow) i równoległy. Skala M (52 mln zdarzeń) powstaje w ok. 20 s na 12 rdzeniach.
- **Zawiera dane osobowe, ale fikcyjne.** Imiona, adresy, telefony, IP i e-maile są wymyślone. Adresy e-mail używają zarezerwowanej domeny `.example` (RFC 2606), więc nigdy nie trafią do prawdziwej skrzynki.

---

## Spis treści

- [Szybki start](#szybki-start)
- [Skale](#skale)
- [Komponenty i struktura wyniku](#komponenty-i-struktura-wyniku)
- [Model danych](#model-danych)
- [Reguły biznesowe](#reguły-biznesowe)
- [Świadomie wprowadzone problemy z danymi](#świadomie-wprowadzone-problemy-z-danymi)
- [Źródła „surowe”](#źródła-surowe)
- [Tryb strumieniowy](#tryb-strumieniowy)
- [Mock API płatności](#mock-api-płatności)
- [Baza transakcyjna i CDC na żywo](#baza-transakcyjna-i-cdc-na-żywo)
- [Generowanie bezpośrednio do GCS](#generowanie-bezpośrednio-do-gcs)
- [Użycie w modułach kursu](#użycie-w-modułach-kursu)
- [Jak to działa pod maską](#jak-to-działa-pod-maską)
- [Rozwój i testy](#rozwój-i-testy)

---

## Szybki start

Wymagania: Python 3.12+ i [`uv`](https://docs.astral.sh/uv/).

```bash
cd datasets
uv sync                                        # instaluje zależności (numpy, pyarrow)

uv run novacart info                           # skale i szacowane wolumeny
uv run novacart generate --scale s -o ./out/s  # ~120 MB, kilka sekund
```

Szybki podgląd w DuckDB:

```sql
-- duckdb
SELECT status, count(*) AS orders, sum(total_amount) AS revenue
FROM read_parquet('out/s/orders/*/*.parquet', hive_partitioning = true)
GROUP BY ALL ORDER BY orders DESC;
```

Załadowanie do BigQuery (schematy z opisami kolumn generuje `novacart schemas`):

```bash
uv run novacart schemas --format bigquery -o ./schemas
bq load --source_format=PARQUET --hive_partitioning_mode=AUTO \
  --hive_partitioning_source_uri_prefix=gs://MOJ-BUCKET/novacart/s/orders \
  novacart_raw.orders "gs://MOJ-BUCKET/novacart/s/orders/*"
```

Opcjonalne zależności instaluje się tylko wtedy, gdy są potrzebne:

```bash
uv sync --extra avro       # zapis w formacie Avro (fastavro)
uv sync --extra pubsub     # stream do Google Pub/Sub
uv sync --extra kafka      # stream do Kafki (confluent-kafka)
uv sync --extra postgres   # replay-oltp do PostgreSQL (psycopg)
uv sync --all-extras       # wszystko
```

---

## Skale

| Skala | Dni | Okres | Klienci | Produkty | Zamówienia | Zdarzenia clickstream | Rozmiar (Parquet) | Czas* |
|---|---|---|---|---|---|---|---|---|
| `xs` | 21 | 11–31.12.2025 | 2 tys. | 500 | ~2 tys. | ~0,16 mln | ~10 MB | 2 s |
| `s` | 61 | 1.11–31.12.2025 | 20 tys. | 4 tys. | ~25 tys. | ~1,9 mln | ~120 MB | 2 s |
| `m` | 365 | cały 2025 | 200 tys. | 30 tys. | ~650 tys. | ~52 mln | ~3 GB | 20 s |
| `l` | 730 | 2024–2025 | 2 mln | 200 tys. | ~10 mln | ~0,8 mld | ~45 GB | kilka min |
| `xl` | 1095 | 2023–2025 | 10 mln | 1 mln | ~110 mln | ~8 mld | ~500 GB | ~1 h |

\* komponenty domyślne, 12 procesów, Apple Silicon. Dla `l` i `xl` generuj bezpośrednio do GCS z maszyny w tym samym regionie co bucket.

Każda skala kończy się 31.12.2025, więc obejmuje Black Friday i okres świąteczny. Okres i rozmiar można zmienić:

```bash
uv run novacart generate --scale m --days 90 --end-date 2025-06-30 --customers 50000 -o ./out/custom
```

---

## Komponenty i struktura wyniku

```bash
uv run novacart generate --scale s -o ./out/s --components entities,orders,clickstream,partners,cdc,documents
uv run novacart generate --scale s -o ./out/s --components all     # to samo
```

Domyślnie generowane są `entities,orders,clickstream,partners`.

```text
out/s/
├── _manifest.json                   # konfiguracja, liczności, opis anomalii (patrz niżej)
├── _SUCCESS
├── customers/part-00000.parquet     # ┐
├── sellers/part-00000.parquet       # │ entities: wymiary w stanie na koniec okresu
├── products/part-00000.parquet      # │ (pełny eksport z bazy transakcyjnej)
├── categories/part-00000.parquet    # │
├── gdpr_requests/part-00000.parquet # ┘
├── orders/dt=2025-11-01/part-00000.parquet       # ┐ orders: partycja = dzień złożenia (UTC)
├── order_items/dt=2025-11-01/part-00000.parquet  # │
├── payments/dt=2025-11-01/part-00000.parquet     # ┘ partycja = dzień transakcji
├── clickstream/dt=2025-11-01/part-00000.parquet  # partycja = dzień PRZYJĘCIA (received_at)
├── partners/                                      # pliki od przewoźników (formaty natywne)
│   ├── speedpost/2025/11/01/SP_TRACKING_20251101.csv
│   ├── europarcel/dt=2025-11-01/europarcel_events_2025-11-01.jsonl.gz
│   └── quickship/quickship_20251101.csv
├── cdc/                                           # strumień zmian bazy (format Debezium)
│   ├── snapshot/<tabela>/snapshot.jsonl.gz
│   └── changes/<tabela>/dt=2025-11-01/changes-2025-11-01.jsonl.gz
└── documents/                                     # dane nieustrukturyzowane (RAG)
    ├── products/product_descriptions.jsonl
    └── policies/{regulamin,zwroty,dostawa,platnosci,prywatnosc,faq}-v*.md
```

Format tabel wybiera się przez `--format parquet|csv|jsonl|avro` (oraz `--compression`). Pliki przewoźników, CDC i dokumenty zawsze mają format natywny dla danego źródła.

> [!NOTE]
> Każda partycja dzienna to dokładnie jeden plik. Problem małych plików (moduły 3–5) poznasz osobno, w kontrolowanych warunkach, a nie jako przypadkowy efekt uboczny generatora.

---

## Model danych

```mermaid
erDiagram
    customers ||--o{ orders : "składa"
    orders ||--|{ order_items : "zawiera"
    products ||--o{ order_items : "dotyczy"
    sellers ||--o{ products : "oferuje"
    categories ||--o{ products : "klasyfikuje"
    categories ||--o{ categories : "rodzic"
    orders ||--o{ payments : "opłacane przez"
    customers ||--o{ gdpr_requests : "składa"
    orders ||..o{ clickstream : "purchase.order_id"
    customers ||..o{ clickstream : "customer_id (gdy zalogowany)"
    orders ||..o{ partner_tracking : "referencja / shipment_id"
```

| Tabela | Klucz | Opis |
|---|---|---|
| `customers` | `customer_id` | Klienci z danymi osobowymi; po wniosku RODO dane osobowe = NULL |
| `sellers` | `seller_id` | Sprzedawcy (fikcyjne firmy z 6 krajów) |
| `products` | `product_id` | Katalog; cena w EUR zmienia się w czasie |
| `categories` | `category_id` | Drzewo 10 kategorii głównych i 38 liści |
| `gdpr_requests` | `request_id` | Zrealizowane wnioski o usunięcie danych |
| `orders` | `order_id` | Zamówienia ze stanem na koniec okresu i pełnym cyklem życia |
| `order_items` | `(order_id, line_number)` | Pozycje zamówień |
| `payments` | `payment_id` | Obciążenia i zwroty środków (próby nieudane też są zapisane) |
| `clickstream` | `event_id`* | Zdarzenia web/mobile; *klucz nie jest unikalny (duplikaty)! |

Pełne schematy z opisem każdej kolumny i flagą `pii`:

```bash
uv run novacart schemas --format bigquery -o ./schemas   # JSON dla bq load / Terraform
uv run novacart schemas --format avro     -o ./schemas   # .avsc
uv run novacart schemas --format postgres -o ./schemas   # DDL bazy transakcyjnej
```

Opisy kolumn są też zapisane w metadanych plików Parquet.

---

## Reguły biznesowe

Te reguły obowiązują w danych i są opisane w dokumentach `documents/policies/`, więc da się je weryfikować testami jakości danych.

| Obszar | Reguła |
|---|---|
| Cykl życia zamówienia | `created → paid → shipped → delivered → (returned)` albo `→ cancelled`; za pobraniem (`cod`): `created → shipped → delivered`, przy czym `paid_at = delivered_at` |
| Brak płatności | Anulowanie po 1 h (przelew tradycyjny: po 72 h); nieudaną płatność można ponowić |
| Kwoty | `total = subtotal − discount + shipping`; `line_amount = quantity × unit_price − discount_amount` |
| Darmowa dostawa | od 399 PLN / 99 EUR / 2 499 CZK (po rabatach); poniżej: 14,99 PLN / 4,99 EUR / 129 CZK |
| Waluta | wynika z kraju klienta: PL → PLN, CZ → CZK, pozostałe → EUR |
| Ceny | lokalne ceny „marketingowe” (…,99 / …9 Kč) wyliczane ze stałego kursu z ceny EUR obowiązującej w chwili zakupu |
| Metody płatności | BLIK tylko w PL, iDEAL tylko w NL |
| Przewoźnicy | SpeedPost (głównie PL), EuroParcel (wszędzie), QuickShip (DE, NL, CZ, SK, LT) |
| Zwroty | prawdopodobieństwo zależne od kategorii (moda ~20%, elektronika ~5%, żywność ~1%) |
| RODO | po anonimizacji klient nie składa nowych zamówień; adresy w historycznych zamówieniach **zostają** (to zadanie dla Ciebie w module 11) |
| Sezonowość | tydzień, miesiąc, Black Friday (×2,8), Cyber Monday, święta, trend wzrostowy 35% r/r; szczyt dobowy wieczorem |
| Skośność | popularność produktów wg rozkładu Zipfa (`--skew`, domyślnie 1,1), aktywność klientów log-normalna |

---

## Świadomie wprowadzone problemy z danymi

### Parametryzowane

| Parametr | Domyślnie | Efekt |
|---|---|---|
| `--duplicate-rate` | 0,01 | Ponownie wysłane zdarzenia clickstream (to samo `event_id`, późniejsze `received_at`) |
| `--late-rate` | 0,03 | Sesje mobilne w trybie offline wysyłane z opóźnieniem (rozkład log-normalny, mediana ~45 min) |
| `--max-lateness-hours` | 72 | Górna granica opóźnienia |
| `--clock-skew-rate` | 0,005 | Urządzenia z błędnym zegarem: `event_ts` przesunięty o 1–48 h, także **w przyszłość** względem `received_at` |
| `--invalid-rate` | 0,002 | Uszkodzone rekordy: literówki w `event_type` (`pageview`, `Product_View`, `add-to-cart`, pusty), `session_id = NULL`, ujemna cena, `customer_id = 0` (nieistniejący) |
| `--skew` | 1,1 | Skośność popularności produktów (gorące klucze w joinach i agregacjach) |
| `--clean` | — | Wyłącza wszystkie problemy i anomalie (dane „podręcznikowe”) |

### Stałe cechy „prawdziwego świata”

- część numerów telefonów zapisana ze spacją po prefiksie, adresy e-mail nie są unikalne,
- kwoty w API płatności w groszach (`int`), a w tabelach jako `DECIMAL(12,2)`,
- pliki SpeedPost w **Windows-1250** z czasem lokalnym bez strefy i przecinkiem dziesiętnym,
- referencja zamówienia w EuroParcel ma postać `NC-<order_id>`, a w pozostałych plikach `<order_id>`,
- SpeedPost dosyła ok. 2% wierszy z poprzedniego dnia (duplikaty między plikami), QuickShip duplikuje ok. 1% wierszy w pliku,
- frazy wyszukiwania zawierają literówki,
- sesje zamówień złożonych tuż po północy zaczynają się poprzedniego dnia.

### Anomalie (`_manifest.json`)

Dla okresów ≥ 14 dni generator wstrzykuje anomalie w losowych (deterministycznych) dniach:

| Anomalia | Co się dzieje |
|---|---|
| `clickstream_android_drop` | Błąd wydania aplikacji: ~85% zdarzeń z Androida nie dociera przez jeden dzień |
| `clickstream_retry_storm` | Awaria kolektora: przez 2 godziny liczba duplikatów rośnie ~15× |
| `order_items_price_in_minor_units` | Jeden sprzedawca przez dzień wysyła `unit_price` w groszach (×100); sumy w `orders` są poprawne, więc `order_items` przestaje się z nimi zgadzać |
| `partner_file_missing` | Plik SpeedPost za jeden dzień nie dociera; jego zawartość przychodzi w pliku z dnia następnego |
| `partner_schema_change` | QuickShip bez zapowiedzi zmienia schemat: `tracking_id` → `tracking_number`, `weight_grams` → `weight_kg`, nowa kolumna `service_level` |

> [!TIP]
> W zadaniach o jakości danych (moduł 29) najpierw spróbuj wykryć anomalie samodzielnie, a dopiero potem porównaj wynik z `_manifest.json`.

---

## Źródła „surowe”

### Pliki przewoźników (`partners`)

| Przewoźnik | Format | Kodowanie | Czas | Pułapki |
|---|---|---|---|---|
| SpeedPost | CSV `;`, przecinek dziesiętny, polskie nagłówki i statusy | Windows-1250 | lokalny, bez strefy (`DD.MM.YYYY HH:MM:SS`) | dosyłane wiersze z poprzedniego dnia, brakujący plik |
| EuroParcel | JSON Lines (gzip), zagnieżdżony | UTF-8 | UTC (`…Z`) | referencja `NC-…` |
| QuickShip | CSV `,` | UTF-8 | z przesunięciem (`+01:00`) | duplikaty w pliku, zmiana schematu |

Statusy: `LABEL_CREATED → PICKED_UP → IN_TRANSIT (1–2×) → OUT_FOR_DELIVERY → (FAILED_DELIVERY → OUT_FOR_DELIVERY) → DELIVERED`.

### Strumień zmian (`cdc`)

Format zbliżony do Debezium z PostgreSQL (`REPLICA IDENTITY FULL`, `decimal.handling.mode=string`):

```json
{"before": {"order_id": 1011679, "status": "paid", "...": "..."},
 "after":  {"order_id": 1011679, "status": "shipped", "carrier": "europarcel", "...": "..."},
 "source": {"connector": "postgresql", "db": "novacart", "schema": "public", "table": "orders",
            "lsn": 112432918467584, "txId": 1756839351056, "ts_ms": 1764590196116, "snapshot": "false"},
 "op": "u", "ts_ms": 1764590196366}
```

- `snapshot/` zawiera stan bazy na początek okresu (`op = "r"`), a `changes/` zmiany partycjonowane po dacie commitu.
- `lsn` rośnie monotonicznie, a zamówienie i jego pozycje mają ten sam `txId`.
- Tabele: `categories`, `sellers`, `customers` (rejestracje, zmiany e-maila, przeprowadzki, zgody, anonimizacja RODO), `products` (nowe produkty, zmiany cen), `orders` (każda zmiana statusu), `order_items`.
- **Gwarancja spójności:** migawka + wszystkie zmiany = tabele z komponentu `entities`/`orders` na koniec okresu (sprawdza to test automatyczny).

### Dokumenty (`documents`)

- `product_descriptions.jsonl` zawiera opisy 2 000 najpopularniejszych produktów (po polsku).
- `policies/*.md` to regulaminy z front matter (`doc_id`, `version`, `valid_from`, `valid_to`). Polityka zwrotów ma dwie wersje (14 → 30 dni w połowie okresu), co przydaje się do ćwiczenia przyrostowego odświeżania indeksu wektorowego.

---

## Tryb strumieniowy

Odtwarza clickstream „na żywo”: bierze zdarzenia przyjęte danego dnia (łącznie ze spóźnionymi z poprzednich dni), mapuje oś czasu na teraz i wysyła je w kolejności przyjęcia.

```bash
# podgląd na konsoli, czas rzeczywisty (od bieżącej godziny dnia)
uv run novacart stream --scale s

# 60× szybciej, do Pub/Sub, z ordering keys = session_id
uv run novacart stream --scale m --speed 60 --sink pubsub --project MOJ-PROJEKT --topic clickstream --ordering

# docelowo ~500 zdarzeń/s do lokalnej Kafki
uv run novacart stream --scale m --rate 500 --sink kafka --bootstrap-servers localhost:9092 --topic clickstream

# do pliku, 10 minut
uv run novacart stream --scale s --sink file --path events.jsonl --duration 600
```

- `received_at` nie jest wysyłane, bo czas przyjęcia ustala odbiorca (np. `publish_time` w Pub/Sub). Każde zdarzenie ma za to `sent_at`.
- Przy `--speed N` opóźnienia skracają się N-krotnie. Przy `--speed 0` zdarzenia lecą najszybciej jak się da, z historycznymi znacznikami czasu.
- Pub/Sub dostaje atrybuty `event_type` i `platform` (do filtrowania subskrypcji). Kafka dostaje klucz `session_id`.

---

## Mock API płatności

```bash
uv run novacart payments-api --scale s --port 8080 --rate-limit 5 --error-rate 0.02

curl -s -H 'Authorization: Bearer novacart-dev-token' \
  'http://127.0.0.1:8080/v1/payments?created_gte=2025-12-01T00:00:00Z&limit=2' | jq
```

```json
{
  "object": "list",
  "data": [{
    "id": "pay_5e2dedb704613403e8bf7ec2", "object": "charge", "created": 1764551209,
    "amount": 64998, "currency": "eur", "status": "succeeded", "failure_code": null,
    "payment_method": {"type": "card", "card": {"brand": "visa", "last4": "1620"}},
    "customer": {"id": "cus_00008184", "email": "schmidt.andreas7@gmx.example"},
    "metadata": {"order_id": "1011682"}, "livemode": false
  }],
  "has_more": true,
  "next_cursor": "eyJhZnRlciI6ICJwYXlfNWUy..."
}
```

| Cecha | Zachowanie |
|---|---|
| Uwierzytelnianie | `Authorization: Bearer <token>` (domyślnie `novacart-dev-token`), w przeciwnym razie 401 |
| Paginacja | `limit` (1–500), kolejna strona przez `starting_after=<next_cursor>` |
| Filtry | `created_gte`, `created_lt` (ISO 8601 lub sekundy od epoki) |
| Rate limiting | token bucket per token, `429` + `Retry-After` |
| Błędy chwilowe | losowe `500`/`503` z prawdopodobieństwem `--error-rate` |
| Opóźnienie | `--latency-ms` (z losowym rozrzutem) |

Endpointy: `GET /v1/payments`, `GET /v1/payments/{id}`, `GET /health`.

---

## Baza transakcyjna i CDC na żywo

`replay-oltp` odtwarza wygenerowany strumień zmian na prawdziwym PostgreSQL (lokalnie, Cloud SQL, AlloyDB). Zmiany są wykonywane jako transakcje w kolejności LSN, opcjonalnie w przyspieszonym czasie rzeczywistym, a Datastream lub Debezium (moduł 26) przechwytują je z WAL.

```bash
uv sync --extra postgres
uv run novacart generate --scale s --components cdc -o ./out/s-cdc

# lokalny PostgreSQL z logical decoding
docker run -d --name novacart-pg -e POSTGRES_PASSWORD=novacart -e POSTGRES_DB=novacart \
  -p 5432:5432 postgres:17 -c wal_level=logical

uv run novacart replay-oltp --cdc-dir ./out/s-cdc/cdc --init-schema \
  --dsn postgresql://postgres:novacart@localhost:5432/novacart --speed 3600   # 1 h danych na sekundę

uv run novacart replay-oltp --cdc-dir ./out/s-cdc/cdc --dry-run              # tylko podgląd SQL
```

Schemat bazy: [`src/novacart_datagen/sql/postgres_oltp.sql`](src/novacart_datagen/sql/postgres_oltp.sql) (klucze obce, `REPLICA IDENTITY FULL`, komentarz o publikacji i slocie replikacji).

---

## Generowanie bezpośrednio do GCS

```bash
gcloud auth application-default login
uv run novacart generate --scale l -o gs://MOJ-BUCKET/novacart/l --workers 16
```

Zapis idzie przez wbudowany w pyarrow klient GCS (Application Default Credentials), bez `gsutil` i lokalnego dysku.

> [!CAUTION]
> Dla skal `l` i `xl` uruchom generator na maszynie wirtualnej **w tym samym regionie co bucket**. Wysyłanie setek GB z laptopa jest wolne, a z innego regionu oznacza koszty transferu. Pamiętaj o regułach lifecycle i o usunięciu danych po zakończeniu modułu.

---

## Użycie w modułach kursu

| Moduł | Komponenty / tryb | Typowe parametry |
|---|---|---|
| 00 — Środowisko | `entities,orders` | `--scale s` |
| 03–05 — Storage, formaty, table formats | `orders`, `clickstream` | `--scale m --format csv/jsonl/avro/parquet` |
| 06–07 — Silniki zapytań, modelowanie | `entities,orders,clickstream` | `--scale m` |
| 11 — Bezpieczeństwo, RODO | `entities,orders` + `gdpr_requests` | `--scale s` |
| 13 — Cloud Storage | `partners` | `--scale m`, notyfikacje GCS |
| 14–17 — BigQuery | wszystkie tabele | `--scale l` do GCS |
| 19–20 — Spark/Dataproc | `clickstream`, `orders` | `--scale l --skew 1.3` |
| 21–24 — Streaming | `stream` | `--sink pubsub --speed 60` |
| 25–26 — Bazy operacyjne, CDC | `cdc` + `replay-oltp` | `--scale s` |
| 26, 36 — Ingest z API | `payments-api` | `--error-rate 0.05 --rate-limit 2` |
| 28 — dbt / Dataform | `entities,orders,clickstream` | `--scale m` |
| 29 — Jakość danych | wszystko, **z anomaliami** | `--scale m` |
| 31–35 — Inne platformy | jak w modułach BigQuery | `--scale m` |
| 42 — ML / GenAI | `documents`, `orders` | `--scale m` |

---

## Jak to działa pod maską

Generator sam w sobie jest małym studium inżynierii danych:

1. **Deterministyczne strumienie losowości.** Każdy fragment danych (np. zamówienia z dnia 137) ma własny generator `numpy` zasiany kluczem `(seed, strumień, dzień)`. Dzięki temu dowolny dzień można policzyć niezależnie i w dowolnej kolejności, a wynik się nie zmieni.
2. **„Świat” zamiast danych.** `World` przechowuje wyłącznie tablice liczbowe: klientów, produkty i sprzedawców posortowanych po dacie utworzenia, kalendarz z sezonowością i harmonogram zmian. Napisy (imiona, adresy, e-maile) powstają na żądanie, wektorowo, przez `pyarrow.compute`.
3. **Spójność czasowa przez próbkowanie prefiksowe.** Zamówienie z chwili *t* może wylosować tylko klienta zarejestrowanego przed *t*: `searchsorted` na posortowanych datach daje liczbę dostępnych encji *k*, a losowanie odbywa się z wagami (rozkład Zipfa) wśród pierwszych *k*.
4. **Pełny cykl życia, różne widoki.** Zamówienie ma komplet znaczników czasu, także tych „z przyszłości”. Migawka obcina je do końca okresu, CDC emituje zmianę w każdym z tych momentów, a przewoźnik generuje z nich zdarzenia śledzenia. Spójność wynika z konstrukcji, a nie z testów.
5. **Partycjonowanie po właściwym czasie.** Dane z dnia *d* trafiają do partycji kilku dni (spóźnione zdarzenia, zwroty środków po tygodniach). Każdy proces przetwarza ciągły blok dni z „rozgrzewką” (dni wcześniejsze) i jednym dniem „wyprzedzenia”, a partycje zapisuje dopiero wtedy, gdy są kompletne: jeden plik na dzień.
6. **Wektoryzacja.** UUID-y, kwoty `DECIMAL` (budowane bezpośrednio z buforów 128-bitowych), znaczniki czasu i napisy powstają bez pętli po wierszach. Pętle w Pythonie zostały tylko tam, gdzie format jest z natury wierszowy (CSV przewoźników, JSON CDC).

---

## Rozwój i testy

```bash
uv sync
uv run pytest -q          # determinizm, integralność, CDC = migawka, API, stream, schematy
uv run ruff check src tests
```

Testy pokrywają m.in.:

- identyczne pliki niezależnie od liczby procesów,
- integralność referencyjną i reguły kwot,
- monotoniczność cyklu życia,
- właściwości clickstreamu (duplikaty, opóźnienia, partycje),
- widoczność anomalii,
- RODO,
- odtworzenie stanu końcowego z CDC,
- paginację, autoryzację i rate limiting API.

> [!NOTE]
> Sinki Pub/Sub i Kafka oraz `replay-oltp` w trybie na żywo wymagają zewnętrznych usług i nie są uruchamiane w testach automatycznych. Testy obejmują logikę generowania zdarzeń i instrukcji SQL (`--dry-run`) oraz odtworzenie stanu w pamięci.
