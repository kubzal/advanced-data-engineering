"""Kontrakt produktu danych „orders” (data mesh) sprawdzany na danych NovaCart.

Lekcja 01.06. Produkt danych to nie tylko tabela: ma właściciela, schemat, gwarancje jakości
i SLO świeżości. Kontrakt zapisany deklaratywnie (TOML) jest sprawdzany automatycznie, zanim
konsumenci (finanse, marketing) zobaczą dane. Skrypt pokazuje też, jak naiwna reguła
wolumenowa myli Black Friday z awarią.

Uruchomienie: cd examples && uv run python 07_data_product_contract.py
"""

from __future__ import annotations

import os
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

DATA = Path(os.environ.get("NOVACART_DATA", Path(__file__).resolve().parents[3] / "data" / "s"))

CONTRACT = tomllib.loads("""
[product]
name        = "sales.orders"
version     = "1.2.0"
owner       = "zespół domeny Sprzedaż (sales-data@novacart.example)"
consumers   = ["finanse: raport przychodów", "marketing: atrybucja kampanii"]
description = "Zamówienia z pozycjami; stan na koniec dnia, partycja = dzień złożenia (UTC)"

[schema.orders]
order_id = "BIGINT"
customer_id = "BIGINT"
status = "VARCHAR"
currency = "VARCHAR"
subtotal_amount = "DECIMAL(12,2)"
discount_amount = "DECIMAL(12,2)"
shipping_amount = "DECIMAL(12,2)"
total_amount = "DECIMAL(12,2)"
created_at = "TIMESTAMP WITH TIME ZONE"

[quality]
unique          = ["order_id"]
not_null        = ["order_id", "customer_id", "status", "currency", "total_amount", "created_at"]
allowed_status  = ["created", "paid", "shipped", "delivered", "returned", "cancelled"]
allowed_currency = ["PLN", "EUR", "CZK"]

[slo]
freshness_hours = 8          # najnowsze zamówienie nie starsze niż 8 h w chwili sprawdzenia
completeness_by = "06:00"    # partycja za dzień D gotowa do 06:00 UTC dnia D+1

[volume]
max_ratio_to_7d_median = 2.0
min_ratio_to_7d_median = 0.5
# Znane wydarzenia biznesowe: dozwolony zakres stosunku do mediany z 7 dni (od, do)
[volume.known_events]
"2025-11-28" = [2.0, 4.0]   # Black Friday
"2025-12-01" = [1.5, 3.0]   # Cyber Monday
"2025-12-24" = [0.3, 0.8]   # Wigilia
"2025-12-25" = [0.3, 0.8]   # Boże Narodzenie
"2025-12-26" = [0.3, 0.8]   # drugi dzień świąt
""")

# Moment sprawdzenia: rano po ostatnim dniu danych (deterministycznie, nie „teraz”).
AS_OF = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    for name in ("orders", "order_items", "customers"):
        pattern = f"{DATA}/{name}/*/*.parquet" if name != "customers" else f"{DATA}/{name}/*.parquet"
        con.execute(
            f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{pattern}', hive_partitioning = true)"
        )
    return con


def check_schema(con) -> tuple[bool, str]:
    actual = {r[0]: r[1] for r in con.execute("DESCRIBE orders").fetchall()}
    diffs = [
        f"{c}: {actual.get(c, 'BRAK')} ≠ {t}"
        for c, t in CONTRACT["schema"]["orders"].items()
        if actual.get(c) != t
    ]
    return not diffs, "; ".join(diffs) or f"{len(CONTRACT['schema']['orders'])} kolumn zgodnych"


def check_quality(con) -> list[tuple[str, bool, str]]:
    q = CONTRACT["quality"]
    out = []
    dup = con.execute("SELECT count(*) - count(DISTINCT order_id) FROM orders").fetchone()[0]
    out.append(("unikalność order_id", dup == 0, f"{dup} duplikatów"))
    nulls = {
        c: con.execute(f"SELECT count(*) FILTER (WHERE {c} IS NULL) FROM orders").fetchone()[0]
        for c in q["not_null"]
    }
    bad = {c: n for c, n in nulls.items() if n}
    out.append(("NOT NULL", not bad, str(bad) if bad else f"{len(nulls)} kolumn bez NULL"))
    for col, key in (("status", "allowed_status"), ("currency", "allowed_currency")):
        vals = [r[0] for r in con.execute(f"SELECT DISTINCT {col} FROM orders").fetchall()]
        extra = sorted(set(vals) - set(q[key]))
        out.append((f"dozwolone wartości {col}", not extra, f"nieznane: {extra}" if extra else "OK"))
    n = con.execute("""SELECT count(*) FROM orders
                       WHERE total_amount <> subtotal_amount - discount_amount + shipping_amount""").fetchone()[
        0
    ]
    out.append(("total = subtotal − discount + shipping", n == 0, f"{n} zamówień niezgodnych"))
    rows = con.execute("""
        WITH items AS (SELECT order_id, sum(line_amount) AS lines FROM order_items GROUP BY 1)
        SELECT o.dt, count(*) FROM orders o JOIN items i USING (order_id)
        WHERE o.subtotal_amount - o.discount_amount <> i.lines GROUP BY 1 ORDER BY 1""").fetchall()
    out.append(
        (
            "Σ order_items.line_amount = subtotal − discount",
            not rows,
            ", ".join(f"{d}: {c} zamówień" for d, c in rows) or "OK",
        )
    )
    orphans = con.execute("""SELECT count(*) FROM orders o
                             WHERE NOT EXISTS (SELECT 1 FROM customers c WHERE c.customer_id = o.customer_id)""").fetchone()[
        0
    ]
    out.append(("customer_id istnieje w customers", orphans == 0, f"{orphans} sierot"))
    return out


def check_slo(con) -> list[tuple[str, bool, str]]:
    # ::TIMESTAMP (przy TimeZone = UTC) zwraca czas UTC bez strefy — bez zależności od pytz
    max_created, max_dt = con.execute("SELECT max(created_at)::TIMESTAMP, max(dt) FROM orders").fetchone()
    lag = AS_OF.replace(tzinfo=None) - max_created
    ok_fresh = lag <= timedelta(hours=CONTRACT["slo"]["freshness_hours"])
    expected_dt = (AS_OF - timedelta(days=1)).date()
    return [
        (
            f"świeżość ≤ {CONTRACT['slo']['freshness_hours']} h",
            ok_fresh,
            f"opóźnienie {lag.seconds // 3600} h {lag.seconds % 3600 // 60} min",
        ),
        ("kompletność: partycja za D-1 istnieje", max_dt >= expected_dt, f"najnowsza partycja {max_dt}"),
    ]


def check_volume(con) -> tuple[list[tuple], list[tuple]]:
    v = CONTRACT["volume"]
    rows = con.execute("""
        WITH d AS (SELECT dt, count(*) AS n FROM orders GROUP BY 1)
        SELECT dt, n, median(n) OVER (ORDER BY dt ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS med
        FROM d ORDER BY dt""").fetchall()
    naive, aware = [], []
    for dt, n, med in rows:
        if med is None:
            continue
        ratio = n / med
        if not v["min_ratio_to_7d_median"] <= ratio <= v["max_ratio_to_7d_median"]:
            naive.append((dt, n, med, ratio))
        lo, hi = v["known_events"].get(str(dt), (v["min_ratio_to_7d_median"], v["max_ratio_to_7d_median"]))
        if not lo <= ratio <= hi:
            aware.append((dt, n, med, ratio))
    return naive, aware


def main() -> None:
    con = connect()
    p = CONTRACT["product"]
    print(f"Produkt danych: {p['name']} v{p['version']}\nWłaściciel:     {p['owner']}")
    print(f"Konsumenci:     {', '.join(p['consumers'])}\nSprawdzenie:    {AS_OF:%Y-%m-%d %H:%M} UTC\n")
    ok, msg = check_schema(con)
    results = [("schemat zgodny z kontraktem", ok, msg), *check_quality(con), *check_slo(con)]
    naive, aware = check_volume(con)
    results.append(
        (
            "wolumen (ze znanymi wydarzeniami)",
            not aware,
            "OK" if not aware else ", ".join(f"{d}: {n} vs mediana {m:.0f}" for d, n, m, _ in aware),
        )
    )
    width = max(len(r[0]) for r in results)
    for name, passed, detail in results:
        print(f"  {'✅' if passed else '❌'} {name:<{width}}  {detail}")
    print("\nNaiwna reguła wolumenowa (bez known_events) zgłosiłaby alarm dla:")
    for dt, n, med, ratio in naive:
        print(f"     {dt}: {n:>5} zamówień, mediana 7 dni {med:>5.0f}, ×{ratio:.2f}")
    failed = [r for r in results if not r[1]]
    print(
        f"\nWynik: {len(results) - len(failed)}/{len(results)} reguł spełnionych →"
        f" {'PUBLIKACJA WSTRZYMANA' if failed else 'publikacja'}"
    )


if __name__ == "__main__":
    main()
