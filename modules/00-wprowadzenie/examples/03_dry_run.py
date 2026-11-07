# examples/03_dry_run.py
"""Szacowanie kosztu zapytania BigQuery przed jego uruchomieniem.

Użycie:
    export GOOGLE_CLOUD_PROJECT=moj-projekt     # projekt, który płaci za zapytania
    uv run python 03_dry_run.py
    uv run python 03_dry_run.py --sql "SELECT title FROM \\`bigquery-public-data.samples.wikipedia\\`"

Wymaga Application Default Credentials (lekcja 00.04): gcloud auth application-default login
"""

from __future__ import annotations

import argparse
import os

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery

PRICE_PER_TIB_USD = 6.25  # cena katalogowa on-demand w chwili pisania; sprawdź aktualny cennik
MIN_BILLED_BYTES = 10 * 2**20  # minimalna opłata: 10 MiB na zapytanie (i na każdą tabelę w zapytaniu)
DEFAULT_LIMIT = 10**9  # 1 GB

DEFAULT_SQL = "SELECT * FROM `bigquery-public-data.samples.wikipedia` LIMIT 10"


def estimate(client: bigquery.Client, sql: str) -> int:
    """Zwraca górne oszacowanie liczby przetworzonych bajtów. Dry run jest bezpłatny."""
    config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=config)
    # Przy dry run zadanie nie jest uruchamiane: statystyki są dostępne od razu.
    return job.total_bytes_processed or 0


def cost_usd(processed_bytes: int) -> float:
    billed = max(processed_bytes, MIN_BILLED_BYTES)
    return billed / 2**40 * PRICE_PER_TIB_USD


def run_guarded(client: bigquery.Client, sql: str, limit_bytes: int) -> None:
    """Uruchamia zapytanie z bezpiecznikiem maximum_bytes_billed."""
    config = bigquery.QueryJobConfig(
        maximum_bytes_billed=limit_bytes,
        use_query_cache=False,
        labels={"course": "ade", "module": "00"},  # etykiety trafiają do INFORMATION_SCHEMA.JOBS i billingu
    )
    try:
        rows = client.query(sql, job_config=config).result()
    except GoogleAPICallError as exc:
        # Szacunek przekroczył limit: BigQuery odrzuca zadanie przed startem, opłata = 0.
        print(f"Zatrzymane przed wykonaniem: {exc.message}")
        return
    for row in rows:
        print(dict(row.items()))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sql", default=DEFAULT_SQL)
    parser.add_argument("--limit-bytes", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--run", action="store_true", help="po szacunku uruchom zapytanie z bezpiecznikiem")
    args = parser.parse_args()

    client = bigquery.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    processed = estimate(client, args.sql)
    print(f"Projekt rozliczany:  {client.project}")
    print(f"Szacowane bajty:     {processed:,} B ({processed / 2**30:.2f} GiB)")
    print(f"Szacowany koszt:     ~{cost_usd(processed):.4f} USD (on-demand, bez darmowego 1 TiB/mies.)")
    print(
        f"Limit bezpiecznika:  {args.limit_bytes:,} B -> {'OK' if processed <= args.limit_bytes else 'ZA DUŻO'}"
    )
    if args.run:
        run_guarded(client, args.sql, args.limit_bytes)


if __name__ == "__main__":
    main()
