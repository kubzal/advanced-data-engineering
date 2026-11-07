# examples/06_duckdb_local_warehouse.py
"""DuckDB jako lokalna „hurtownia”: zapytania analityczne na plikach Parquet NovaCart, bez chmury.

    cd datasets && uv run novacart generate --scale s -o ../data/s     # jednorazowo
    cd modules/00-wprowadzenie/examples
    uv run python 06_duckdb_local_warehouse.py                         # domyślnie data/s

Każde zapytanie czyta pliki bezpośrednio (bez ładowania), a skrypt mierzy czas i pokazuje,
ile danych DuckDB musiał odczytać dzięki projekcji kolumn i filtrom partycji.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("NOVACART_DATA", REPO_ROOT / "data" / "s"))


def show(con: duckdb.DuckDBPyConnection, title: str, sql: str) -> None:
    started = time.perf_counter()
    rel = con.sql(sql)
    rows = rel.fetchall()
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"\n### {title}  ({elapsed_ms:.0f} ms)")
    widths = [max(len(str(c)), *(len(f"{r[i]}") for r in rows)) for i, c in enumerate(rel.columns)]
    print("  ".join(c.ljust(w) for c, w in zip(rel.columns, widths, strict=True)))
    for r in rows:
        print("  ".join(f"{v}".ljust(w) for v, w in zip(r, widths, strict=True)))


def main() -> None:
    if not (DATA / "_SUCCESS").exists():
        raise SystemExit(f"Brak danych w {DATA}. Uruchom: uv run novacart generate --scale s -o ../data/s")

    con = duckdb.connect()  # baza w pamięci; nic nie zapisujemy na dysk
    for table in ("orders", "order_items", "clickstream", "products", "categories"):
        pattern = "*/*.parquet" if table in {"orders", "order_items", "clickstream"} else "*.parquet"
        con.sql(
            f"CREATE VIEW {table} AS SELECT * FROM read_parquet("
            f"'{(DATA / table / pattern).as_posix()}', hive_partitioning = true)"
        )

    # 1. Przychód per kraj i waluta. Kwoty są w walucie lokalnej, więc NIE sumujemy PLN z EUR.
    show(
        con,
        "1. Przychód (zamówienia nieanulowane) per kraj wysyłki i waluta",
        """
        SELECT shipping_country AS kraj, currency AS waluta,
               count(*) AS zamowienia,
               sum(total_amount) AS przychod,
               round(avg(total_amount), 2) AS sredni_koszyk
        FROM orders
        WHERE status <> 'cancelled'
        GROUP BY ALL
        ORDER BY zamowienia DESC
        """,
    )

    # 2. Lejek: ile sesji dochodzi do kolejnych kroków. Liczymy sesje, nie zdarzenia,
    #    więc duplikaty zdarzeń nie zawyżają wyniku.
    show(
        con,
        "2. Lejek konwersji (sesje) w grudniu 2025",
        """
        WITH s AS (
            SELECT session_id,
                   bool_or(event_type = 'product_view')   AS viewed,
                   bool_or(event_type = 'add_to_cart')    AS carted,
                   bool_or(event_type = 'begin_checkout') AS checkout,
                   bool_or(event_type = 'purchase')       AS purchased
            FROM clickstream
            WHERE dt >= DATE '2025-12-01' AND session_id IS NOT NULL
            GROUP BY session_id
        )
        SELECT count(*) AS sesje,
               count(*) FILTER (viewed)    AS z_ogladaniem_produktu,
               count(*) FILTER (carted)    AS z_koszykiem,
               count(*) FILTER (checkout)  AS z_checkoutem,
               count(*) FILTER (purchased) AS z_zakupem,
               round(100.0 * count(*) FILTER (purchased) / count(*), 2) AS konwersja_proc
        FROM s
        """,
    )

    # 3. Jakość danych: zdublowane event_id (ponowne wysyłki z aplikacji).
    show(
        con,
        "3. Duplikaty event_id per dzień przyjęcia (5 najgorszych dni)",
        """
        SELECT dt, count(*) AS zdarzenia,
               count(*) - count(DISTINCT event_id) AS nadmiarowe_kopie,
               round(100.0 * (count(*) - count(DISTINCT event_id)) / count(*), 2) AS proc
        FROM clickstream
        GROUP BY dt
        ORDER BY nadmiarowe_kopie DESC
        LIMIT 5
        """,
    )

    # 4. Skośność: jaki udział sprzedanych sztuk mają najpopularniejsze produkty (rozkład Zipfa).
    show(
        con,
        "4. Udział top N produktów w sprzedanych sztukach",
        """
        WITH p AS (
            SELECT product_id, sum(quantity) AS szt,
                   row_number() OVER (ORDER BY sum(quantity) DESC) AS rnk
            FROM order_items GROUP BY product_id
        )
        SELECT n AS top_n,
               round(100.0 * sum(szt) FILTER (rnk <= n) / sum(szt), 1) AS udzial_proc
        FROM p, (VALUES (10), (100), (400)) t(n)
        GROUP BY n ORDER BY n
        """,
    )

    # 5. Ile danych trzeba przeczytać? EXPLAIN ANALYZE pokazuje pliki i bajty faktycznie odczytane.
    #    Ten sam mechanizm (partition pruning) zobaczysz w BigQuery jako „bytes processed”.
    print("\n### 5. Partition pruning i projekcja kolumn (EXPLAIN ANALYZE)")
    one_day = "WHERE dt = DATE '2025-12-24'"
    for label, sql in [
        ("pełny skan, 1 kolumna", "SELECT count(DISTINCT event_id) FROM clickstream"),
        ("1 dzień, 1 kolumna   ", f"SELECT count(DISTINCT event_id) FROM clickstream {one_day}"),
        ("1 dzień, *           ", f"SELECT * FROM clickstream {one_day}"),
    ]:
        plan = con.sql(f"EXPLAIN ANALYZE {sql}").fetchall()[0][1]
        keep = ("Data Read", "Scanning Files", "Total Time")
        facts = [ln.strip("│ ").strip() for ln in plan.splitlines() if any(k in ln for k in keep)]
        print(f"  {label}  " + " | ".join(dict.fromkeys(facts)))


if __name__ == "__main__":
    main()
