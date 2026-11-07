-- exercise/solution/sql/control_queries.sql
-- Zapytania kontrolne na tabelach zewnętrznych NovaCart (skala S, seed 42).
-- Uruchomienie (z katalogu exercise/):
--   bq query --project_id="$PROJECT_ID" --use_legacy_sql=false \
--     --maximum_bytes_billed=1000000000 --label=course:ade --label=module:00 \
--     < solution/sql/control_queries.sql

-- Q1. Liczba zamówień, liczba partycji i zakres dat.
-- Filtr na dt jest wymagany (require_partition_filter = true) i pozwala pominąć zbędne pliki.
SELECT
  COUNT(*)           AS orders,
  COUNT(DISTINCT dt) AS partitions,
  MIN(dt)            AS first_day,
  MAX(dt)            AS last_day
FROM novacart_raw.orders
WHERE dt BETWEEN DATE '2025-11-01' AND DATE '2025-12-31';

-- Q2. Zamówienia według statusu na koniec okresu.
SELECT status, COUNT(*) AS orders
FROM novacart_raw.orders
WHERE dt BETWEEN DATE '2025-11-01' AND DATE '2025-12-31'
GROUP BY status
ORDER BY orders DESC;

-- Q3. Przychód według waluty. Kwot w różnych walutach nie sumujemy razem!
SELECT currency, COUNT(*) AS orders, SUM(total_amount) AS revenue
FROM novacart_raw.orders
WHERE dt BETWEEN DATE '2025-11-01' AND DATE '2025-12-31'
GROUP BY currency
ORDER BY currency;

-- Q4. Black Friday (28.11.2025): jedna partycja, więc zapytanie czyta jeden plik.
SELECT currency, COUNT(*) AS orders, SUM(total_amount) AS revenue
FROM novacart_raw.orders
WHERE dt = DATE '2025-11-28'
GROUP BY currency
ORDER BY currency;

-- Q5. Klienci: liczba wszystkich i zanonimizowanych po wniosku RODO.
SELECT
  COUNT(*)                                AS customers,
  COUNTIF(gdpr_erased_at IS NOT NULL)     AS gdpr_erased
FROM novacart_raw.customers;
