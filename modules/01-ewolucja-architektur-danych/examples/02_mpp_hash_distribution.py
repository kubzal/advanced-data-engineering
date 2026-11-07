"""Symulacja hurtowni MPP (shared-nothing): dystrybucja hash, skew i redystrybucja przy JOIN.

W hurtowni MPP (Teradata, Netezza, Redshift, Synapse dedicated pool) każdy wiersz trafia na jeden
węzeł według funkcji skrótu klucza dystrybucji: node = hash(key) mod N. Ten skrypt rozkłada tabele
NovaCart na N węzłów według różnych kluczy i mierzy:

1. skew: ile wierszy ma najbardziej obciążony węzeł w stosunku do średniej
   (zapytanie kończy się wtedy, gdy skończy najwolniejszy węzeł),
2. ruch sieciowy przy JOIN: ile wierszy trzeba przesłać, żeby pary do złączenia były na tym samym węźle.

Uruchomienie (z katalogu examples/):
    env -u VIRTUAL_ENV uv run python 02_mpp_hash_distribution.py            # 8 węzłów
    env -u VIRTUAL_ENV uv run python 02_mpp_hash_distribution.py --nodes 32
"""

from __future__ import annotations

import argparse
import os
import zlib
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

DATA = Path(os.environ.get("NOVACART_DATA", Path(__file__).resolve().parents[3] / "data" / "s"))


def read(name: str, columns: list[str] | None = None) -> pa.Table:
    path = DATA / name
    if (path / "part-00000.parquet").exists():
        return pq.read_table(path / "part-00000.parquet", columns=columns)
    return ds.dataset(path, format="parquet", partitioning="hive").to_table(columns=columns)


def row_bytes(name: str) -> float:
    """Średni rozmiar wiersza bez kompresji (z metadanych Parquet) — przybliża bajty w sieci."""
    files = sorted((DATA / name).rglob("*.parquet"))
    total = rows = 0
    for f in files:
        meta = pq.ParquetFile(f).metadata
        rows += meta.num_rows
        total += sum(meta.row_group(i).total_byte_size for i in range(meta.num_row_groups))
    return total / rows


def node_of(values: pa.ChunkedArray, nodes: int) -> np.ndarray:
    """Deterministyczna funkcja skrótu → numer węzła (jak hash distribution w MPP)."""
    if pa.types.is_integer(values.type):
        x = values.to_numpy().astype(np.uint64)
        # Mieszanie bitów (splitmix64), żeby kolejne klucze nie trafiały na kolejne węzły „po kolei”.
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        x = x ^ (x >> np.uint64(31))
        return (x % np.uint64(nodes)).astype(np.int64)
    return np.array([zlib.crc32(v.encode()) % nodes for v in values.to_pylist()], dtype=np.int64)


def skew_report(label: str, nodes_arr: np.ndarray, nodes: int) -> tuple[str, int, float, int]:
    counts = np.bincount(nodes_arr, minlength=nodes)
    return label, int(counts.max()), counts.max() / counts.mean(), int((counts == 0).sum())


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--nodes", type=int, default=8, help="liczba węzłów (AMP/slice) w klastrze")
    args = parser.parse_args()
    n = args.nodes

    orders = read("orders", ["order_id", "customer_id", "shipping_country"])
    items = read("order_items", ["order_id", "line_number", "seller_id", "product_id"])
    customers = read("customers", ["customer_id", "country"])
    b_orders, b_items, b_customers = row_bytes("orders"), row_bytes("order_items"), row_bytes("customers")

    print(
        f"Klaster: {n} węzłów · orders {orders.num_rows:,} · order_items {items.num_rows:,} · "
        f"customers {customers.num_rows:,}\n"
    )

    # --- 1. Skew w zależności od klucza dystrybucji ------------------------------------------
    print("1) Rozkład wierszy na węzły (skew = max / średnia; 1,00 = idealnie równo)")
    print(f"   {'Tabela i klucz dystrybucji':42s} {'max wierszy':>12s} {'skew':>7s} {'puste węzły':>12s}")
    reports = [
        skew_report("orders BY order_id", node_of(orders["order_id"], n), n),
        skew_report("orders BY customer_id", node_of(orders["customer_id"], n), n),
        skew_report("orders BY shipping_country", node_of(orders["shipping_country"], n), n),
        skew_report("order_items BY order_id", node_of(items["order_id"], n), n),
        skew_report("order_items BY seller_id", node_of(items["seller_id"], n), n),
        skew_report("order_items BY product_id", node_of(items["product_id"], n), n),
    ]
    for label, mx, skew, empty in reports:
        print(f"   {label:42s} {mx:>12,} {skew:>7.2f} {empty:>12}")

    # Najwięksi sprzedawcy — skąd bierze się skew przy kluczu seller_id
    sellers, cnt = np.unique(items["seller_id"].to_numpy(), return_counts=True)
    top = np.argsort(cnt)[::-1][:3]
    share = ", ".join(f"seller {sellers[i]}: {cnt[i] / cnt.sum():.1%}" for i in top)
    print(f"   Najwięksi sprzedawcy (udział w pozycjach): {share}\n")

    # --- 2. Ruch sieciowy przy JOIN -----------------------------------------------------------
    print("2) JOIN orders ⋈ order_items ON order_id — ile danych trzeba przesłać między węzłami?")
    print(f"   {'Wariant dystrybucji':58s} {'wiersze':>9s} {'MB':>8s}")

    items_by_order = node_of(items["order_id"], n)  # gdzie wiersz MUSI być do złączenia
    orders_by_order = node_of(orders["order_id"], n)

    # a) obie tabele rozłożone po order_id: złączenie lokalne (co-located join)
    print(f"   {'a) orders BY order_id, items BY order_id (co-located)':58s} {0:>9,} {0:>8.2f}")

    # b) items rozłożone po seller_id: każdą pozycję spoza „właściwego” węzła trzeba przesłać
    items_by_seller = node_of(items["seller_id"], n)
    moved = int((items_by_seller != items_by_order).sum())
    print(
        f"   {'b) items BY seller_id → redystrybucja items po order_id':58s} "
        f"{moved:>9,} {moved * b_items / 1e6:>8.2f}"
    )

    # c) orders po customer_id (dobry do joinu z customers), items po order_id
    orders_by_customer = node_of(orders["customer_id"], n)
    moved = int((orders_by_customer != orders_by_order).sum())
    print(
        f"   {'c) orders BY customer_id → redystrybucja orders po order_id':58s} "
        f"{moved:>9,} {moved * b_orders / 1e6:>8.2f}"
    )

    # d) broadcast mniejszej tabeli: kopia orders na każdy węzeł
    moved = orders.num_rows * (n - 1)
    print(f"   {'d) broadcast orders na wszystkie węzły':58s} {moved:>9,} {moved * b_orders / 1e6:>8.2f}\n")

    print("3) JOIN orders ⋈ customers ON customer_id")
    print(f"   {'Wariant dystrybucji':58s} {'wiersze':>9s} {'MB':>8s}")
    moved = int((orders_by_order != orders_by_customer).sum())
    print(
        f"   {'a) orders BY order_id → redystrybucja orders po customer_id':58s} "
        f"{moved:>9,} {moved * b_orders / 1e6:>8.2f}"
    )
    print(f"   {'b) orders BY customer_id, customers BY customer_id':58s} {0:>9,} {0:>8.2f}")
    moved = customers.num_rows * (n - 1)
    print(
        f"   {'c) broadcast customers na wszystkie węzły':58s} {moved:>9,} {moved * b_customers / 1e6:>8.2f}"
    )
    print(f"\n   Uwaga: odsetek przesuwanych wierszy przy losowym kluczu ≈ (N-1)/N = {(n - 1) / n:.1%}")


if __name__ == "__main__":
    main()
