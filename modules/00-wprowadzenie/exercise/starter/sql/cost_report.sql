-- exercise/starter/sql/cost_report.sql
-- Raport kosztów zapytań modułu 00 na podstawie INFORMATION_SCHEMA.JOBS.
-- Uwaga: widok jest regionalny, np. `region-europe-central2`.INFORMATION_SCHEMA.JOBS_BY_PROJECT.

-- TODO(zadanie): dla zadań z etykietą module=00 z ostatnich 7 dni policz liczbę zadań,
-- sumę total_bytes_processed i total_bytes_billed oraz koszt wg ceny katalogowej on-demand.
-- Podpowiedź: etykiety są w kolumnie labels (ARRAY<STRUCT<key STRING, value STRING>>).
