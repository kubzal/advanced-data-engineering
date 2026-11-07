"""Schema-on-write vs schema-on-read na plikach przewoźnika QuickShip.

W połowie okresu QuickShip bez zapowiedzi zmienia format pliku:
`tracking_id` → `tracking_number`, `weight_grams` → `weight_kg`, nowa kolumna `service_level`.

Porównujemy trzy podejścia:

1. schema-on-write (hurtownia): schemat jest sprawdzany przy ładowaniu; plik niezgodny jest odrzucany,
2. schema-on-read „naiwnie” (wczesny data lake): wszystko się ładuje, a problem wychodzi w zapytaniach,
3. schema-on-read z warstwą mapowania: schemat interpretujemy przy odczycie, świadomie.

Uruchomienie (z katalogu examples/):
    env -u VIRTUAL_ENV uv run python 04_schema_on_read.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import duckdb

DATA = Path(os.environ.get("NOVACART_DATA", Path(__file__).resolve().parents[3] / "data" / "s"))
FILES = sorted((DATA / "partners" / "quickship").glob("quickship_*.csv"))

# Kontrakt uzgodniony z przewoźnikiem na początku współpracy.
EXPECTED_HEADER = ["tracking_id", "order_ref", "status", "event_time", "city", "country_code", "weight_grams"]


def schema_on_write() -> None:
    print("1) SCHEMA-ON-WRITE — walidacja przy ładowaniu (jak COPY/LOAD do tabeli w hurtowni)")
    loaded, rejected, rows_loaded, rows_rejected, first_bad = 0, 0, 0, 0, None
    for path in FILES:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            n = sum(1 for _ in reader)
        if header == EXPECTED_HEADER:
            loaded += 1
            rows_loaded += n
        else:
            rejected += 1
            rows_rejected += n
            first_bad = first_bad or (path.name, header)
    print(f"   załadowane pliki: {loaded}, odrzucone: {rejected}")
    print(f"   wiersze załadowane: {rows_loaded:,}, odrzucone: {rows_rejected:,}")
    if first_bad:
        name, header = first_bad
        missing = sorted(set(EXPECTED_HEADER) - set(header))
        extra = sorted(set(header) - set(EXPECTED_HEADER))
        print(f"   pierwszy odrzucony plik: {name}")
        print(f"     brakuje kolumn: {missing}; nieznane kolumny: {extra}")
    print(
        "   → problem widać NATYCHMIAST (alert przy ładowaniu), ale dane od tego dnia nie trafiają do hurtowni,"
    )
    print("     dopóki ktoś nie zmieni schematu tabeli i procesu ETL.\n")


def schema_on_read(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"""
        CREATE VIEW raw AS
        SELECT * FROM read_csv('{DATA}/partners/quickship/quickship_*.csv',
                               union_by_name = true, filename = true, header = true)
    """)
    cols = [r[0] for r in con.execute("DESCRIBE raw").fetchall()]
    print("2) SCHEMA-ON-READ „naiwnie” — wszystkie pliki czytane jednym wzorcem")
    print(f"   kolumny widoczne w widoku: {cols}")
    q = """
        SELECT substr(regexp_extract(filename, '(\\d{8})', 1), 1, 6) AS month,  -- miesiąc pliku
               count(*)                       AS events,
               count(DISTINCT tracking_id)    AS parcels,
               round(avg(weight_grams) / 1000, 2) AS avg_kg
        FROM raw GROUP BY 1 ORDER BY 1
    """
    print("   Raport „średnia waga paczki” napisany przez analityka w listopadzie:")
    print(f"   {'miesiąc':>8s} {'zdarzenia':>10s} {'paczki':>8s} {'śr. kg':>8s}")
    for month, events, parcels, avg_kg in con.execute(q).fetchall():
        print(f"   {month:>8s} {events:>10,} {parcels:>8,} {avg_kg:>8}")
    nulls = con.execute("SELECT count(*) FROM raw WHERE tracking_id IS NULL").fetchone()[0]
    print(f"   → zapytanie DZIAŁA i nie zgłasza błędu, ale {nulls:,} zdarzeń ma tracking_id = NULL:")
    print("     liczba paczek w grudniu jest po cichu zaniżona, a średnia waga liczona tylko z części")
    print("     miesiąca. Nikt nie dostał alertu.\n")


def schema_on_read_mapped(con: duckdb.DuckDBPyConnection) -> None:
    print("3) SCHEMA-ON-READ z warstwą mapowania — interpretacja obu wersji formatu")
    con.execute("""
        CREATE VIEW quickship_events AS
        SELECT coalesce(tracking_id, tracking_number)                          AS tracking_id,
               order_ref, status, event_time, city, country_code,
               coalesce(weight_grams, CAST(round(weight_kg * 1000) AS BIGINT)) AS weight_grams,
               service_level,
               CASE WHEN tracking_number IS NULL THEN 'v1' ELSE 'v2' END       AS format_version,
               filename
        FROM raw
    """)
    q = """
        SELECT substr(regexp_extract(filename, '(\\d{8})', 1), 1, 6) AS month,  -- miesiąc pliku
               count(*)                       AS events,
               count(DISTINCT tracking_id)    AS parcels,
               round(avg(weight_grams) / 1000, 2) AS avg_kg
        FROM quickship_events GROUP BY 1 ORDER BY 1
    """
    print(f"   {'miesiąc':>8s} {'zdarzenia':>10s} {'paczki':>8s} {'śr. kg':>8s}")
    for month, events, parcels, avg_kg in con.execute(q).fetchall():
        print(f"   {month:>8s} {events:>10,} {parcels:>8,} {avg_kg:>8}")
    first_v2 = con.execute(
        "SELECT min(filename) FROM quickship_events WHERE format_version = 'v2'"
    ).fetchone()[0]
    print(f"   pierwszy plik w formacie v2: {Path(first_v2).name}")
    print("   → wynik poprawny, ale tylko dlatego, że KTOŚ wykrył zmianę i dopisał mapowanie.")


def main() -> None:
    print(f"Pliki QuickShip: {len(FILES)} ({FILES[0].name} … {FILES[-1].name})\n")
    schema_on_write()
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    schema_on_read(con)
    schema_on_read_mapped(con)


if __name__ == "__main__":
    main()
