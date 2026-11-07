-- exercise/starter/sql/control_queries.sql
-- Zapytania kontrolne na tabelach zewnętrznych NovaCart (skala S, seed 42).
-- Uruchomienie (z katalogu exercise/starter):
--   bq query --project_id="$PROJECT_ID" --use_legacy_sql=false \
--     --maximum_bytes_billed=1000000000 --label=course:ade --label=module:00 \
--     < sql/control_queries.sql

-- Q1. Liczba zamówień, liczba partycji (dni) i zakres dat w tabeli novacart_raw.orders.
-- TODO(zadanie): napisz zapytanie. Pamiętaj, że tabela wymaga filtra na kolumnie partycji.

-- Q2. Zamówienia według statusu (created, paid, shipped, delivered, returned, cancelled).
-- TODO(zadanie)

-- Q3. Liczba zamówień i przychód (total_amount) według waluty.
-- TODO(zadanie): zastanów się, czy można sumować kwoty w PLN, EUR i CZK razem.

-- Q4. Liczba zamówień i przychód według waluty w Black Friday (2025-11-28).
-- TODO(zadanie): zapytanie powinno czytać tylko jedną partycję.

-- Q5. Liczba klientów i liczba klientów zanonimizowanych po wniosku RODO (gdpr_erased_at).
-- TODO(zadanie)
