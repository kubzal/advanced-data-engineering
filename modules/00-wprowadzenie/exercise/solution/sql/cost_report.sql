-- exercise/solution/sql/cost_report.sql
-- Koszt zapytań modułu 00 z INFORMATION_SCHEMA.JOBS (dane z ostatnich 7 dni).
-- Widok jest regionalny: zapytania na tabelach w europe-central2 są w region-europe-central2,
-- a zapytania do bigquery-public-data (lekcja 00.03) w region-us.
SELECT
  job_type,
  statement_type,
  COUNT(*)                                              AS jobs,
  SUM(total_bytes_processed)                            AS bytes_processed,
  SUM(total_bytes_billed)                               AS bytes_billed,
  ROUND(SUM(total_bytes_billed) / POW(2, 40), 6)        AS tib_billed,
  -- Koszt wg ceny katalogowej on-demand (sprawdź aktualny cennik); Free Tier pomniejsza go do 0.
  ROUND(SUM(total_bytes_billed) / POW(2, 40) * 6.25, 4) AS list_price_usd
FROM `region-europe-central2`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND EXISTS (SELECT 1 FROM UNNEST(labels) AS l WHERE l.key = 'module' AND l.value = '00')
GROUP BY job_type, statement_type
ORDER BY bytes_billed DESC;

-- Pojedyncze zadania: które zapytanie kosztowało najwięcej?
SELECT
  creation_time,
  job_id,
  total_bytes_processed,
  total_bytes_billed,
  LEFT(REGEXP_REPLACE(query, r'\s+', ' '), 80) AS query_start
FROM `region-europe-central2`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND job_type = 'QUERY'
ORDER BY total_bytes_billed DESC
LIMIT 10;
