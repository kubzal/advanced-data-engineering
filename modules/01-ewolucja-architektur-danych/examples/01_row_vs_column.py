"""Row store vs column store na danych NovaCart.

Te same zamówienia ładujemy do SQLite (row store, B-drzewo po kluczu) i do DuckDB
(column store, kompresja, wykonanie wektorowe). Następnie mierzymy:

1. obciążenie OLTP: odczyt jednego zamówienia po kluczu i aktualizacje pojedynczych wierszy,
2. obciążenie OLAP: agregację przychodu po kraju i miesiącu,
3. ile bajtów każdy silnik musi przeczytać, żeby odpowiedzieć na zapytanie analityczne.

Uruchomienie (z katalogu examples/):
    env -u VIRTUAL_ENV uv run python 01_row_vs_column.py            # domyślnie 20 kopii skali S
    env -u VIRTUAL_ENV uv run python 01_row_vs_column.py --copies 5

Dane: wygeneruj wcześniej `uv run novacart generate --scale s -o ../data/s` (z katalogu datasets/).
"""

from __future__ import annotations

import argparse
import os
import random
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

DATA = Path(os.environ.get("NOVACART_DATA", Path(__file__).resolve().parents[3] / "data" / "s"))

COLUMNS = [
    "order_id", "customer_id", "status", "currency", "platform", "payment_method", "promo_code",
    "items_count", "subtotal_amount", "discount_amount", "shipping_amount", "total_amount",
    "shipping_country", "shipping_city", "shipping_postal_code", "shipping_street", "carrier",
    "shipment_id", "created_at", "paid_at", "shipped_at", "delivered_at", "cancelled_at",
    "returned_at", "updated_at",
]  # fmt: skip
ANALYTIC_COLUMNS = ["shipping_country", "created_at", "total_amount", "status"]
ANALYTIC_SQL = """
    SELECT shipping_country,
           strftime('%Y-%m', created_at) AS month,
           count(*)                      AS orders,
           sum(total_amount)             AS revenue
    FROM orders
    WHERE status <> 'cancelled'
    GROUP BY 1, 2
    ORDER BY 1, 2
"""


def load_orders(copies: int) -> pa.Table:
    """Wczytuje zamówienia ze skali S i powiela je `copies` razy z nowymi kluczami."""
    base = ds.dataset(DATA / "orders", format="parquet", partitioning="hive").to_table(columns=COLUMNS)
    # Upraszczamy typy tak, by obie bazy przechowywały to samo: kwoty w groszach (int64),
    # czas jako tekst ISO (SQLite nie ma typu TIMESTAMP, przechowuje tekst albo liczbę).
    cols = {}
    for name in COLUMNS:
        col = base[name]
        if pa.types.is_decimal(col.type):
            col = pc.cast(pc.multiply(col, 100), pa.int64())
        elif pa.types.is_timestamp(col.type):
            col = pc.strftime(col, format="%Y-%m-%d %H:%M:%S")
        cols[name] = col
    base = pa.table(cols)
    step = int(pc.max(base["order_id"]).as_py()) + 1
    parts = []
    for i in range(copies):
        parts.append(base.set_column(0, "order_id", pc.add(base["order_id"], i * step)))
    return pa.concat_tables(parts).combine_chunks()


def timed(fn, repeat: int = 3) -> float:
    """Zwraca medianę czasu wykonania w sekundach."""
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


def build_sqlite(path: Path, table: pa.Table) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    ints = {
        "customer_id",
        "items_count",
        "subtotal_amount",
        "discount_amount",
        "shipping_amount",
        "total_amount",
    }
    col_defs = ", ".join(
        f"{c} INTEGER PRIMARY KEY" if c == "order_id" else f"{c} {'INTEGER' if c in ints else 'TEXT'}"
        for c in COLUMNS
    )
    con.execute(f"CREATE TABLE orders ({col_defs})")
    placeholders = ", ".join("?" * len(COLUMNS))
    rows = zip(*(table[c].to_pylist() for c in COLUMNS), strict=True)
    with con:
        con.executemany(f"INSERT INTO orders VALUES ({placeholders})", rows)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return con


def build_duckdb(path: Path, table: pa.Table) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path))
    con.execute("SET threads = 8")
    con.register("src", table)
    con.execute(
        "CREATE TABLE orders AS SELECT * REPLACE (CAST(created_at AS TIMESTAMP) AS created_at) FROM src"
    )
    con.unregister("src")
    con.execute("ALTER TABLE orders ADD PRIMARY KEY (order_id)")
    con.execute("CHECKPOINT")
    return con


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--copies", type=int, default=20, help="ile razy powielić zamówienia ze skali S")
    args = parser.parse_args()

    table = load_orders(args.copies)
    n = table.num_rows
    print(f"Zamówienia: {n:,} wierszy × {len(COLUMNS)} kolumn (dane: {DATA}, kopie: {args.copies})\n")

    rnd = random.Random(42)
    ids = table["order_id"].to_pylist()
    lookup_ids = rnd.sample(ids, 2_000)
    update_ids = rnd.sample(ids, 500)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        t0 = time.perf_counter()
        lite = build_sqlite(tmp / "orders.sqlite", table)
        t_lite_load = time.perf_counter() - t0
        t0 = time.perf_counter()
        duck = build_duckdb(tmp / "orders.duckdb", table)
        t_duck_load = time.perf_counter() - t0
        pq.write_table(table, tmp / "orders.parquet", compression="zstd", row_group_size=1_000_000)

        # --- 1. Rozmiar na dysku ------------------------------------------------------------
        page_size = lite.execute("PRAGMA page_size").fetchone()[0]
        page_count = lite.execute("PRAGMA page_count").fetchone()[0]
        size_lite = (tmp / "orders.sqlite").stat().st_size
        size_duck = (tmp / "orders.duckdb").stat().st_size
        size_pq = (tmp / "orders.parquet").stat().st_size

        # --- 2. OLTP: odczyt po kluczu -------------------------------------------------------
        def lite_lookups() -> None:
            for oid in lookup_ids:
                lite.execute("SELECT * FROM orders WHERE order_id = ?", (oid,)).fetchone()

        def duck_lookups() -> None:
            for oid in lookup_ids:
                duck.execute("SELECT * FROM orders WHERE order_id = ?", [oid]).fetchone()

        t_lite_lookup = timed(lite_lookups) / len(lookup_ids)
        t_duck_lookup = timed(duck_lookups) / len(lookup_ids)

        # --- 3. OLTP: aktualizacje pojedynczych wierszy, każda we własnej transakcji ---------
        def lite_updates() -> None:
            for oid in update_ids:
                with lite:
                    lite.execute(
                        "UPDATE orders SET status = 'shipped', updated_at = '2026-01-01 00:00:00' WHERE order_id = ?",
                        (oid,),
                    )

        def duck_updates() -> None:
            for oid in update_ids:
                duck.execute("BEGIN")
                duck.execute(
                    "UPDATE orders SET status = 'shipped', updated_at = '2026-01-01 00:00:00' WHERE order_id = ?",
                    [oid],
                )
                duck.execute("COMMIT")

        t_lite_upd = timed(lite_updates, repeat=1) / len(update_ids)
        t_duck_upd = timed(duck_updates, repeat=1) / len(update_ids)

        # --- 4. OLAP: agregacja po kraju i miesiącu -----------------------------------------
        r_lite = lite.execute(ANALYTIC_SQL).fetchall()
        r_duck = duck.execute(ANALYTIC_SQL).fetchall()
        assert [(a, b, c, d) for a, b, c, d in r_lite] == [(a, b, c, int(d)) for a, b, c, d in r_duck]
        t_lite_agg = timed(lambda: lite.execute(ANALYTIC_SQL).fetchall())
        t_duck_agg = timed(lambda: duck.execute(ANALYTIC_SQL).fetchall())

        # --- 5. Ile bajtów trzeba przeczytać do zapytania analitycznego? --------------------
        # Row store: każda strona tabeli zawiera całe wiersze, więc skan czyta wszystkie strony.
        bytes_lite = page_count * page_size
        # Column store (Parquet jako przenośny odpowiednik): tylko kolumny użyte w zapytaniu.
        meta = pq.ParquetFile(tmp / "orders.parquet").metadata
        bytes_pq_all = 0
        bytes_pq_used = 0
        for rg in range(meta.num_row_groups):
            for ci in range(meta.num_columns):
                col = meta.row_group(rg).column(ci)
                bytes_pq_all += col.total_compressed_size
                if col.path_in_schema in ANALYTIC_COLUMNS:
                    bytes_pq_used += col.total_compressed_size

        lite.close()
        duck.close()

    print("Rozmiar danych na dysku")
    print(
        f"  {'SQLite (row store, B-drzewo)':34s} {human(size_lite):>12s}  ({page_count:,} stron × {page_size} B)"
    )
    print(f"  {'DuckDB (column store)':34s} {human(size_duck):>12s}")
    print(f"  {'Parquet zstd (column store)':34s} {human(size_pq):>12s}")
    print(f"  Czas ładowania: SQLite {t_lite_load:.1f} s, DuckDB {t_duck_load:.1f} s\n")

    print(f"{'Operacja':44s} {'SQLite':>12s} {'DuckDB':>12s} {'Zwycięzca':>12s}")
    rows = [
        ("OLTP: odczyt 1 zamówienia po kluczu", t_lite_lookup, t_duck_lookup),
        ("OLTP: UPDATE 1 wiersza + COMMIT", t_lite_upd, t_duck_upd),
        ("OLAP: przychód per kraj i miesiąc", t_lite_agg, t_duck_agg),
    ]
    for name, a, b in rows:
        winner = "SQLite" if a < b else "DuckDB"
        ratio = max(a, b) / min(a, b)
        print(f"{name:44s} {a * 1000:>9.3f} ms {b * 1000:>9.3f} ms {winner:>7s} ×{ratio:,.0f}")

    print("\nBajty do przeczytania przez zapytanie analityczne (4 z 25 kolumn)")
    print(f"  {'Row store (wszystkie strony tabeli)':40s} {human(bytes_lite):>12s}")
    print(f"  {'Column store (tylko 4 kolumny, Parquet)':40s} {human(bytes_pq_used):>12s}")
    print(f"  Stosunek: ×{bytes_lite / bytes_pq_used:,.0f} mniej danych w column store")
    print(f"  (wszystkie kolumny w Parquet: {human(bytes_pq_all)})")


if __name__ == "__main__":
    main()
