"""Orkiestracja generowania: dzieli okres na bloki dni i przetwarza je równolegle.

Wynik nie zależy od liczby procesów: każdy dzień ma własny, deterministyczny seed,
a każdy proces odtwarza ``World`` z tej samej konfiguracji.
"""

from __future__ import annotations

import gzip
import json
import math
import multiprocessing as mp
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime

import numpy as np
import pyarrow as pa

from . import __version__
from .arrays import US_PER_DAY
from .cdc import CDC_TABLES, change_events_for_day, snapshot_events, to_jsonl
from .clickstream import generate_clickstream
from .config import ALL_COMPONENTS, Config
from .documents import policies, product_descriptions
from .entities import entity_tables
from .logistics import partner_files_for_date
from .orders import items_table, orders_table, payments_table
from .schemas import conform
from .world import World
from .writers import Sink

ENTITY_CHUNK = 1_000_000
PAYMENT_LOOKBACK_DAYS = 40  # najpóźniejszy zwrot środków: ~38 dni po zamówieniu
_WORLD: World | None = None


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _init_worker(cfg: Config) -> None:
    global _WORLD
    _WORLD = World(cfg)


class _Pending:
    """Bufor fragmentów tabeli należących do przyszłych partycji dziennych.

    Płatność może powstać do ~40 dni po zamówieniu, a zdarzenie clickstream dotrzeć kilka dni
    po swoim dniu. Zamiast pisać wiele małych plików, zbieramy fragmenty i zapisujemy jeden plik
    na partycję, gdy wszystkie dni źródłowe zostały przetworzone.
    """

    def __init__(self, world: World, ts_column: str):
        self.world = world
        self.ts_column = ts_column
        self.parts: dict[int, list[pa.Table]] = defaultdict(list)

    def add(self, table: pa.Table, min_day: int, max_day: int) -> None:
        """Dodaje fragmenty należące do partycji z przedziału [min_day, max_day]."""
        if table.num_rows == 0:
            return
        table = table.sort_by(self.ts_column)
        days = (table.column(self.ts_column).cast(pa.int64()).to_numpy() - self.world.start_us) // US_PER_DAY
        bounds = np.flatnonzero(np.diff(days)) + 1
        starts = np.concatenate([[0], bounds])
        ends = np.concatenate([bounds, [len(days)]])
        for s, e in zip(starts, ends):
            day = int(days[s])
            if min_day <= day <= max_day and day < self.world.cfg.days:
                self.parts[day].append(table.slice(int(s), int(e - s)))

    def pop(self, day: int) -> pa.Table | None:
        parts = self.parts.pop(day, None)
        if not parts:
            return None
        return pa.concat_tables(parts).sort_by(self.ts_column)


def _lookbacks(cfg: Config) -> tuple[int, int]:
    click = math.ceil((cfg.max_lateness_hours + 7) / 24) + 1
    return click, PAYMENT_LOOKBACK_DAYS


def _process_days(
    days: list[int], components: tuple[str, ...], root: str, fmt: str, compression: str | None
) -> Counter:
    world = _WORLD
    assert world is not None
    sink = Sink(root, fmt, compression)
    counts: Counter = Counter()
    payments = _Pending(world, "created_at")
    clicks = _Pending(world, "received_at")
    first, last = days[0], days[-1]
    click_lb, pay_lb = _lookbacks(world.cfg)
    want_orders = "orders" in components
    want_clicks = "clickstream" in components

    def flush(day: int) -> None:
        day_str = world.dates[day].isoformat()
        if want_orders and (pay := payments.pop(day)) is not None:
            sink.write_table(f"payments/dt={day_str}/part-00000", conform(pay, "payments"))
            counts["payments"] += pay.num_rows
        if want_clicks and (cs := clicks.pop(day)) is not None:
            sink.write_table(f"clickstream/dt={day_str}/part-00000", conform(cs, "clickstream"))
            counts["clickstream"] += cs.num_rows

    # Blok odpowiada za partycje [first, last]. Fragmenty tych partycji powstają też z dni
    # wcześniejszych (spóźnione zdarzenia, zwroty środków) oraz z dnia last + 1 (sesja zamówienia
    # złożonego tuż po północy zaczęła się poprzedniego dnia), więc te dni też generujemy.
    if want_orders:
        for d in range(max(0, first - pay_lb), first):
            payments.add(payments_table(world, world.orders_for_day(d)), first, last)
    if want_clicks:
        for d in range(max(0, first - click_lb), first):
            clicks.add(generate_clickstream(world, d), first, last)

    for d in range(first, min(last + 2, world.cfg.days)):
        batch = world.orders_for_day(d)
        if want_orders:
            payments.add(payments_table(world, batch), first, last)
        if want_clicks:
            clicks.add(generate_clickstream(world, d, batch), first, last)
        if d - 1 >= first:
            flush(d - 1)
        if d > last:
            break
        day_str = world.dates[d].isoformat()
        if want_orders:
            o = conform(orders_table(world, batch), "orders")
            sink.write_table(f"orders/dt={day_str}/part-00000", o)
            counts["orders"] += o.num_rows
            it = conform(items_table(world, batch), "order_items")
            sink.write_table(f"order_items/dt={day_str}/part-00000", it)
            counts["order_items"] += it.num_rows
        if "partners" in components:
            for relpath, data in partner_files_for_date(world, d):
                sink.write_bytes(relpath, data)
                counts["partner_files"] += 1
        if "cdc" in components:
            day_str = world.dates[d].isoformat()
            for table, events in change_events_for_day(world, d).items():
                if events:
                    sink.write_bytes(
                        f"cdc/changes/{table}/dt={day_str}/changes-{day_str}.jsonl.gz",
                        gzip.compress(to_jsonl(events), mtime=0),
                    )
                    counts[f"cdc.{table}"] += len(events)
    flush(last)  # ostatni dzień okresu (gdy nie było dnia last + 1); dla pozostałych to no-op
    return counts


def _chunks(n_days: int, workers: int) -> list[list[int]]:
    size = max(1, math.ceil(n_days / max(1, workers * 3)))
    return [list(range(i, min(n_days, i + size))) for i in range(0, n_days, size)]


def _write_entities(world: World, sink: Sink, counts: Counter) -> None:
    for name, table in entity_tables(world).items():
        for i, start in enumerate(range(0, max(table.num_rows, 1), ENTITY_CHUNK)):
            part = conform(table.slice(start, ENTITY_CHUNK), name)
            sink.write_table(f"{name}/part-{i:05d}", part)
        counts[name] += table.num_rows


def _write_documents(world: World, sink: Sink, counts: Counter) -> None:
    sink.write_bytes("documents/products/product_descriptions.jsonl", product_descriptions(world))
    for fname, text in policies(world).items():
        sink.write_bytes(f"documents/policies/{fname}", text.encode("utf-8"))
        counts["documents"] += 1


def _write_cdc_snapshot(world: World, sink: Sink, counts: Counter) -> None:
    for table, events in snapshot_events(world).items():
        if events:
            sink.write_bytes(
                f"cdc/snapshot/{table}/snapshot.jsonl.gz", gzip.compress(to_jsonl(events), mtime=0)
            )
            counts[f"cdc_snapshot.{table}"] += len(events)


def run_generate(
    cfg: Config,
    output: str,
    components: Iterable[str],
    fmt: str = "parquet",
    compression: str | None = None,
    workers: int = 1,
) -> dict:
    components = tuple(c for c in ALL_COMPONENTS if c in set(components))
    unknown = set(components) - set(ALL_COMPONENTS)
    if unknown:
        raise ValueError(f"Nieznane komponenty: {sorted(unknown)}")
    started = time.time()
    sink = Sink(output, fmt, compression)
    _log(
        f"NovaCart datagen {__version__}: skala={cfg.scale}, okres {cfg.start_date}..{cfg.end_date} "
        f"({cfg.days} dni), seed={cfg.seed}, komponenty={','.join(components)}, format={fmt}, procesy={workers}"
    )
    world = World(cfg)
    _log(
        f"  świat gotowy: {cfg.customers:,} klientów, {cfg.products:,} produktów, {cfg.sellers:,} sprzedawców, "
        f"~{int(world.day_orders.sum()):,} zamówień"
    )
    counts: Counter = Counter()

    if "entities" in components:
        _write_entities(world, sink, counts)
        _log("  zapisano wymiary (entities)")
    if "documents" in components:
        _write_documents(world, sink, counts)
        _log("  zapisano dokumenty")
    if "cdc" in components:
        _write_cdc_snapshot(world, sink, counts)
        _log("  zapisano migawkę CDC")

    daily = tuple(c for c in components if c in ("orders", "clickstream", "partners", "cdc"))
    if daily:
        chunks = _chunks(cfg.days, workers)
        done = 0
        if workers <= 1:
            global _WORLD
            _WORLD = world
            for chunk in chunks:
                counts.update(_process_days(chunk, daily, output, fmt, compression))
                done += len(chunk)
                _log(f"  [{done * 100 // cfg.days:3d}%] dni {done}/{cfg.days}")
        else:
            ctx = mp.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=workers, mp_context=ctx, initializer=_init_worker, initargs=(cfg,)
            ) as pool:
                futures = {
                    pool.submit(_process_days, chunk, daily, output, fmt, compression): len(chunk)
                    for chunk in chunks
                }
                for fut in as_completed(futures):
                    counts.update(fut.result())
                    done += futures[fut]
                    _log(f"  [{done * 100 // cfg.days:3d}%] dni {done}/{cfg.days}")

    manifest = {
        "generator": "novacart-datagen",
        "version": __version__,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "duration_seconds": round(time.time() - started, 1),
        "output": output,
        "format": fmt,
        "compression": compression,
        "components": list(components),
        "config": cfg.to_dict(),
        "row_counts": dict(sorted(counts.items())),
        "anomalies": [a.to_dict() for a in world.anomalies],
        "cdc_tables": list(CDC_TABLES) if "cdc" in components else [],
    }
    sink.write_bytes("_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    sink.write_bytes("_SUCCESS", b"")
    _log(f"Gotowe w {manifest['duration_seconds']} s → {output}")
    for k, v in manifest["row_counts"].items():
        _log(f"  {k:28s} {v:>14,}")
    return manifest
