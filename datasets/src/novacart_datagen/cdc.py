"""Strumień zmian (CDC) bazy transakcyjnej NovaCart w formacie zbliżonym do Debezium.

Każda zmiana to koperta::

    {"before": {...} | null, "after": {...} | null, "op": "r|c|u|d",
     "source": {"connector": "postgresql", "db": "novacart", "schema": "public", "table": "orders",
                "lsn": 123, "txId": 456, "ts_ms": 1700000000000, "snapshot": "false"},
     "ts_ms": 1700000000250}

Konwencje zgodne z typową konfiguracją Debezium:

* ``before`` zawiera pełny wiersz (tabela z ``REPLICA IDENTITY FULL``),
* kwoty jako napisy (``decimal.handling.mode=string``),
* znaczniki czasu jako ISO 8601 UTC, daty jako ``YYYY-MM-DD``,
* ``lsn`` rośnie monotonicznie z czasem commitu; zamówienie i jego pozycje mają ten sam ``txId``.

Migawka początkowa (``op = "r"``) opisuje stan bazy na początek okresu. Zmiany są
partycjonowane po dacie commitu (UTC).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import numpy as np
import pyarrow as pa

from .arrays import NULL_TS, US_PER_DAY
from .entities import categories_table, customers_columns, products_columns, sellers_columns
from .orders import LIFECYCLE, items_columns, orders_columns

if TYPE_CHECKING:
    from .world import World

CDC_TABLES = ("categories", "sellers", "customers", "products", "orders", "order_items")
PRIMARY_KEYS = {
    "categories": ("category_id",),
    "sellers": ("seller_id",),
    "customers": ("customer_id",),
    "products": ("product_id",),
    "orders": ("order_id",),
    "order_items": ("order_id", "line_number"),
}
ORDER_LOOKBACK_DAYS = 45  # zamówienie może zmienić stan (np. zwrot) do kilkudziesięciu dni po złożeniu
_SEQ = {"orders": 0, "order_items": 1, "customers": 20, "products": 21, "sellers": 22, "categories": 23}
_DB_ITEM_COLUMNS = (
    "order_id",
    "line_number",
    "product_id",
    "seller_id",
    "quantity",
    "unit_price",
    "discount_amount",
    "line_amount",
    "currency",
)


def _py(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _rows(columns: dict[str, pa.Array], keep: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    names = list(keep or columns)
    lists = [columns[k].to_pylist() for k in names]
    return [{k: _py(v) for k, v in zip(names, vals)} for vals in zip(*lists)]


def _envelope(
    table: str, op: str, before: dict | None, after: dict | None, t_us: int, seq: int, snapshot: bool = False
) -> dict[str, Any]:
    lsn = int(t_us) * 64 + seq
    ts_ms = int(t_us) // 1000
    return {
        "before": before,
        "after": after,
        "source": {
            "version": "novacart-datagen",
            "connector": "postgresql",
            "name": "novacart",
            "ts_ms": ts_ms,
            "snapshot": "true" if snapshot else "false",
            "db": "novacart",
            "schema": "public",
            "table": table,
            "txId": lsn // 64 if not snapshot else 0,
            "lsn": lsn,
        },
        "op": op,
        "ts_ms": ts_ms + 250,
    }


def snapshot_events(world: World) -> dict[str, list[dict[str, Any]]]:
    """Stan bazy na początek okresu jako zdarzenia ``op = "r"``."""
    t = world.start_us
    c, s, p = world.customers, world.sellers, world.products
    out: dict[str, list[dict[str, Any]]] = {}
    out["categories"] = [
        _envelope("categories", "r", None, r, t, 0, True) for r in categories_table().to_pylist()
    ]
    sel = np.nonzero(s.joined_us < t)[0]
    out["sellers"] = [
        _envelope("sellers", "r", None, r, t, 0, True) for r in _rows(sellers_columns(world, sel))
    ]
    cust = np.nonzero(c.signup_us < t)[0]
    out["customers"] = [
        _envelope("customers", "r", None, r, t, 0, True) for r in _rows(customers_columns(world, cust, t))
    ]
    prod = np.nonzero(p.created_us < t)[0]
    out["products"] = [
        _envelope("products", "r", None, r, t, 0, True) for r in _rows(products_columns(world, prod, t))
    ]
    out["orders"] = []
    out["order_items"] = []
    return out


def _in_day(values: np.ndarray, lo: int, hi: int, end: int) -> np.ndarray:
    return (values != NULL_TS) & (values >= lo) & (values < hi) & (values <= end)


def change_events_for_day(world: World, day: int) -> dict[str, list[dict[str, Any]]]:
    """Wszystkie zmiany zatwierdzone w dniu ``day`` (indeks w okresie), posortowane po LSN."""
    lo = world.day_start_us(day)
    hi = lo + US_PER_DAY
    end = world.end_us
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in CDC_TABLES}

    # -- zamówienia i pozycje ----------------------------------------------------------------------
    for od in range(max(0, day - ORDER_LOOKBACK_DAYS), day + 1):
        batch = world.orders_for_day(od)
        life = batch.lifecycle()
        for j, name in enumerate(LIFECYCLE):
            t = life[:, j]
            mask = _in_day(t, lo, hi, end)
            # zdarzenia w tej samej chwili (np. płatność za pobraniem przy doręczeniu) to jedna zmiana
            for k in range(j + 1, life.shape[1]):
                mask &= life[:, k] != t
            rows = np.nonzero(mask)[0]
            if len(rows) == 0:
                continue
            t_rows = t[rows]
            after = _rows(orders_columns(world, batch, rows, t_rows))
            if name == "created":
                before: list[dict | None] = [None] * len(rows)
                op = "c"
                item_idx = np.nonzero(np.isin(batch.item_row, rows))[0]
                item_cols = items_columns(world, batch, item_idx)
                items = _rows(item_cols, _DB_ITEM_COLUMNS)
                item_t = batch.created[batch.item_row[item_idx]]
                for r, it, line in zip(items, item_t, batch.item_line[item_idx]):
                    out["order_items"].append(_envelope("order_items", "c", None, r, int(it), int(line)))
            else:
                prev = np.where(
                    (life[rows] != NULL_TS) & (life[rows] < t_rows[:, None]), life[rows], NULL_TS
                ).max(axis=1)
                before = _rows(orders_columns(world, batch, rows, prev))  # type: ignore[assignment]
                op = "u"
            for b, a, tt in zip(before, after, t_rows):
                out["orders"].append(_envelope("orders", op, b, a, int(tt), _SEQ["orders"]))

    # -- klienci ------------------------------------------------------------------------------------------
    c = world.customers
    created = np.nonzero(_in_day(c.signup_us, lo, hi, end) & (c.signup_us >= world.start_us))[0]
    for r, t in zip(_rows(customers_columns(world, created, c.signup_us[created])), c.signup_us[created]):
        out["customers"].append(_envelope("customers", "c", None, r, int(t), _SEQ["customers"]))
    for changes in (c.email_change_us, c.move_us, c.consent_change_us, c.erased_us):
        idx = np.nonzero(_in_day(changes, lo, hi, end))[0]
        if len(idx) == 0:
            continue
        t = changes[idx]
        before = _rows(customers_columns(world, idx, t - 1))
        after = _rows(customers_columns(world, idx, t))
        for b, a, tt in zip(before, after, t):
            out["customers"].append(_envelope("customers", "u", b, a, int(tt), _SEQ["customers"]))

    # -- produkty -----------------------------------------------------------------------------------------------
    p = world.products
    created = np.nonzero(_in_day(p.created_us, lo, hi, end) & (p.created_us >= world.start_us))[0]
    for r, t in zip(_rows(products_columns(world, created, p.created_us[created])), p.created_us[created]):
        out["products"].append(_envelope("products", "c", None, r, int(t), _SEQ["products"]))
    for j in range(p.change_us.shape[1]):
        idx = np.nonzero(_in_day(p.change_us[:, j], lo, hi, end))[0]
        if len(idx) == 0:
            continue
        t = p.change_us[idx, j]
        before = _rows(products_columns(world, idx, t - 1))
        after = _rows(products_columns(world, idx, t))
        for b, a, tt in zip(before, after, t):
            out["products"].append(_envelope("products", "u", b, a, int(tt), _SEQ["products"]))

    # -- sprzedawcy ----------------------------------------------------------------------------------------------
    s = world.sellers
    joined = np.nonzero(_in_day(s.joined_us, lo, hi, end) & (s.joined_us >= world.start_us))[0]
    for r, t in zip(_rows(sellers_columns(world, joined)), s.joined_us[joined]):
        out["sellers"].append(_envelope("sellers", "c", None, r, int(t), _SEQ["sellers"]))

    for events in out.values():
        events.sort(key=lambda e: e["source"]["lsn"])
    return out


def to_jsonl(events: list[dict[str, Any]]) -> bytes:
    return ("".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n" for e in events)).encode()
