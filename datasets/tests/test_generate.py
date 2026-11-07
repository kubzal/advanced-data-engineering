"""Testy całego zbioru: determinizm, integralność referencyjna, reguły biznesowe."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds

from novacart_datagen.config import Config
from novacart_datagen.generate import run_generate


def _read(root: Path, name: str) -> pa.Table:
    return ds.dataset(root / name, format="parquet", partitioning="hive").to_table()


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "_manifest.json"
    }


def test_deterministic_regardless_of_workers(dataset: Path, dataset_parallel: Path) -> None:
    a, b = _hashes(dataset), _hashes(dataset_parallel)
    assert a.keys() == b.keys()
    diff = [k for k in a if a[k] != b[k]]
    assert not diff, f"Pliki różnią się między 1 a 3 procesami: {diff[:5]}"


def test_same_seed_same_data_different_seed_different_data(tmp_path: Path) -> None:
    cfg = Config.from_scale("xs", days=3, anomalies=False)
    run_generate(cfg, str(tmp_path / "a"), ["orders"], workers=1)
    run_generate(cfg, str(tmp_path / "b"), ["orders"], workers=1)
    run_generate(Config.from_scale("xs", days=3, seed=7, anomalies=False), str(tmp_path / "c"), ["orders"])
    assert _hashes(tmp_path / "a") == _hashes(tmp_path / "b")
    assert _hashes(tmp_path / "a") != _hashes(tmp_path / "c")


def test_manifest_and_success_marker(dataset: Path) -> None:
    manifest = json.loads((dataset / "_manifest.json").read_text())
    assert (dataset / "_SUCCESS").exists()
    assert manifest["row_counts"]["orders"] == _read(dataset, "orders").num_rows
    assert {a["kind"] for a in manifest["anomalies"]} >= {"clickstream_android_drop", "partner_schema_change"}


def test_one_file_per_daily_partition(dataset: Path, cfg: Config) -> None:
    for name in ("orders", "order_items", "payments", "clickstream"):
        partitions = sorted((dataset / name).glob("dt=*"))
        assert len(partitions) == cfg.days, name
        assert all(len(list(p.glob("*.parquet"))) == 1 for p in partitions), name


def test_referential_integrity(dataset: Path) -> None:
    orders = _read(dataset, "orders")
    items = _read(dataset, "order_items")
    customers = _read(dataset, "customers")
    products = _read(dataset, "products")
    sellers = _read(dataset, "sellers")
    payments = _read(dataset, "payments")

    assert pc.count_distinct(orders["order_id"]).as_py() == orders.num_rows
    assert set(items["order_id"].to_pylist()) == set(orders["order_id"].to_pylist())
    assert set(orders["customer_id"].to_pylist()) <= set(customers["customer_id"].to_pylist())
    assert set(items["product_id"].to_pylist()) <= set(products["product_id"].to_pylist())
    assert set(products["seller_id"].to_pylist()) <= set(sellers["seller_id"].to_pylist())
    assert set(payments["order_id"].to_pylist()) <= set(orders["order_id"].to_pylist())


def test_order_amounts_consistent(dataset: Path, world) -> None:
    orders = _read(dataset, "orders").to_pandas()
    items = _read(dataset, "order_items").to_pandas()
    bug = world.anomaly("order_items_price_in_minor_units")
    items["gross"] = items["unit_price"] * items["quantity"]
    per_order = items.groupby("order_id").agg(
        gross=("gross", "sum"), lines=("line_number", "count"), sellers=("seller_id", lambda s: set(s))
    )
    merged = orders.set_index("order_id").join(per_order)
    assert (merged["lines"] == merged["items_count"]).all()
    affected = merged["sellers"].apply(lambda s: bug.details["seller_id"] in s) & (
        merged["created_at"].dt.date.astype(str) == bug.date
    )
    ok = merged[~affected]
    assert (ok["gross"] == ok["subtotal_amount"]).all()
    assert (ok["total_amount"] == ok["subtotal_amount"] - ok["discount_amount"] + ok["shipping_amount"]).all()
    # anomalia: ceny jednego sprzedawcy w groszach zamiast w złotych
    assert (merged[affected]["gross"] > merged[affected]["subtotal_amount"]).all()
    assert affected.sum() > 0


def test_order_lifecycle_is_monotonic(dataset: Path, world) -> None:
    o = _read(dataset, "orders").to_pandas()
    assert (o["created_at"] <= o["updated_at"]).all()
    shipped = o.dropna(subset=["shipped_at"])
    assert (shipped["shipped_at"] > shipped["created_at"]).all()
    delivered = o.dropna(subset=["delivered_at"])
    assert (delivered["delivered_at"] > delivered["shipped_at"]).all()
    assert (o.loc[o.status == "cancelled", "shipped_at"].isna()).all()
    assert (o.loc[o.status == "returned", "returned_at"].notna()).all()
    assert o["updated_at"].max().value // 1000 <= world.end_us


def test_clickstream_properties(dataset: Path, cfg: Config) -> None:
    cs = _read(dataset, "clickstream")
    n = cs.num_rows
    dups = n - pc.count_distinct(cs["event_id"]).as_py()
    assert 0.005 < dups / n < 0.05  # duplicate_rate 1% + burza retry
    lateness = pc.subtract(cs["received_at"], cs["event_ts"]).cast(pa.int64()).to_numpy() / 1e6
    assert (lateness > 3600).sum() > 0, "powinny istnieć zdarzenia spóźnione o ponad godzinę"
    assert (lateness < 0).sum() > 0, "powinny istnieć zdarzenia z zegarem w przyszłości"
    assert lateness.max() <= cfg.max_lateness_hours * 3600 + 7 * 3600 + 49 * 3600
    # każde zamówienie ma zdarzenie purchase z tym samym order_id (poza dniem awarii Androida
    # i zamówieniami z pierwszych minut okresu, których sesja zaczęła się przed okresem)
    purchases = set(pc.drop_null(cs.filter(pc.equal(cs["event_type"], "purchase"))["order_id"]).to_pylist())
    orders = set(_read(dataset, "orders")["order_id"].to_pylist())
    assert len(orders - purchases) / len(orders) < 0.02
    # partycja = dzień przyjęcia
    part_day = pc.cast(cs["dt"], pa.string()) if "dt" in cs.column_names else None
    if part_day is not None:
        received_day = pc.strftime(cs["received_at"], format="%Y-%m-%d")
        assert pc.all(pc.equal(pc.cast(part_day, pa.string()), received_day)).as_py()


def test_android_drop_anomaly_visible(dataset: Path, world) -> None:
    cs = _read(dataset, "clickstream")
    drop = world.anomaly("clickstream_android_drop")
    day = pc.strftime(cs["event_ts"], format="%Y-%m-%d")
    android = pc.equal(cs["platform"], "android")
    per_day = pa.table({"day": day, "android": android}).group_by("day").aggregate([("android", "mean")])
    share = dict(zip(per_day["day"].to_pylist(), per_day["android_mean"].to_pylist()))
    others = [v for k, v in share.items() if k != drop.date]
    assert share[drop.date] < 0.5 * np.median(others)


def test_customers_pii_and_gdpr(dataset: Path) -> None:
    c = _read(dataset, "customers").to_pandas()
    erased = c[c.gdpr_erased_at.notna()]
    assert len(erased) > 0
    assert erased[["first_name", "last_name", "email", "phone", "street_address"]].isna().all().all()
    active = c[c.gdpr_erased_at.isna()]
    assert active.email.str.endswith(".example").all()
    gdpr = _read(dataset, "gdpr_requests").to_pandas()
    assert set(gdpr.customer_id) == set(erased.customer_id)


def test_money_is_exact_decimal(dataset: Path) -> None:
    o = _read(dataset, "orders")
    assert pa.types.is_decimal(o.schema.field("total_amount").type)
    assert isinstance(o["total_amount"][0].as_py(), Decimal)
