"""Odtwarzanie strumienia CDC na prawdziwej bazie PostgreSQL (``novacart replay-oltp``).

Wejściem jest katalog ``cdc/`` wygenerowany przez ``novacart generate --components cdc``.
Narzędzie wykonuje INSERT/UPDATE w kolejności LSN, grupując zmiany w transakcje (``txId``),
opcjonalnie w przyspieszonym czasie rzeczywistym. Dzięki temu baza zachowuje się jak
działający system sklepu, a Datastream lub Debezium (moduł 26) przechwytują prawdziwe zmiany.
"""

from __future__ import annotations

import gzip
import heapq
import json
import sys
import time
from collections.abc import Iterable, Iterator
from importlib import resources
from itertools import groupby
from typing import Any

import pyarrow.fs as pafs

from .cdc import CDC_TABLES, PRIMARY_KEYS


def ddl() -> str:
    return resources.files("novacart_datagen").joinpath("sql/postgres_oltp.sql").read_text(encoding="utf-8")


def _fs(root: str) -> tuple[pafs.FileSystem, str]:
    if "://" in root:
        return pafs.FileSystem.from_uri(root)
    return pafs.LocalFileSystem(), root


def _read_jsonl_gz(fs: pafs.FileSystem, path: str) -> list[dict[str, Any]]:
    with fs.open_input_stream(path, compression=None) as f:
        data = gzip.decompress(f.read())
    return [json.loads(line) for line in data.splitlines() if line]


def snapshot(root: str) -> Iterator[dict[str, Any]]:
    fs, base = _fs(root)
    for table in CDC_TABLES:
        path = f"{base}/snapshot/{table}/snapshot.jsonl.gz"
        if fs.get_file_info(path).type == pafs.FileType.File:
            yield from _read_jsonl_gz(fs, path)


def change_days(root: str) -> list[str]:
    fs, base = _fs(root)
    days: set[str] = set()
    for table in CDC_TABLES:
        sel = pafs.FileSelector(f"{base}/changes/{table}", allow_not_found=True)
        for info in fs.get_file_info(sel):
            if info.type == pafs.FileType.Directory and info.base_name.startswith("dt="):
                days.add(info.base_name[3:])
    return sorted(days)


def changes(root: str, until: str | None = None) -> Iterator[dict[str, Any]]:
    """Zmiany ze wszystkich tabel, scalone po LSN, dzień po dniu."""
    fs, base = _fs(root)
    for day in change_days(root):
        if until and day > until:
            break
        streams = []
        for table in CDC_TABLES:
            path = f"{base}/changes/{table}/dt={day}/changes-{day}.jsonl.gz"
            if fs.get_file_info(path).type == pafs.FileType.File:
                streams.append(_read_jsonl_gz(fs, path))
        yield from heapq.merge(*streams, key=lambda e: e["source"]["lsn"])


def statement(event: dict[str, Any]) -> tuple[str, list[Any]]:
    """Zamienia zdarzenie CDC na instrukcję SQL z parametrami (styl psycopg: %s)."""
    table = event["source"]["table"]
    op = event["op"]
    pk = PRIMARY_KEYS[table]
    if op in ("c", "r"):
        row = event["after"]
        cols = list(row)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
        return sql, [row[c] for c in cols]
    if op == "u":
        row = event["after"]
        cols = [c for c in row if c not in pk]
        sql = (
            f"UPDATE {table} SET {', '.join(f'{c} = %s' for c in cols)} "
            f"WHERE {' AND '.join(f'{k} = %s' for k in pk)}"
        )
        return sql, [row[c] for c in cols] + [row[k] for k in pk]
    if op == "d":
        row = event["before"]
        return f"DELETE FROM {table} WHERE {' AND '.join(f'{k} = %s' for k in pk)}", [row[k] for k in pk]
    raise ValueError(f"Nieznana operacja {op!r}")


def apply_to_memory(
    events: Iterable[dict[str, Any]], state: dict[str, dict[tuple, dict]] | None = None
) -> dict[str, dict[tuple, dict]]:
    """Aplikuje zdarzenia do słownika {tabela: {klucz: wiersz}} (testy i ćwiczenia bez bazy)."""
    state = state if state is not None else {t: {} for t in CDC_TABLES}
    for e in events:
        table = e["source"]["table"]
        pk = PRIMARY_KEYS[table]
        if e["op"] in ("c", "r", "u"):
            row = e["after"]
            state[table][tuple(row[k] for k in pk)] = row
        elif e["op"] == "d":
            row = e["before"]
            state[table].pop(tuple(row[k] for k in pk), None)
    return state


def run_replay(
    root: str,
    dsn: str | None,
    init_schema: bool = False,
    speed: float = 0.0,
    until: str | None = None,
    dry_run: bool = False,
    skip_snapshot: bool = False,
) -> int:
    if dry_run:
        n = 0
        for e in [] if skip_snapshot else snapshot(root):
            sql, params = statement(e)
            n += 1
            if n <= 5:
                print(sql, params)
        for e in changes(root, until):
            sql, params = statement(e)
            n += 1
            if n <= 10:
                print(sql, params)
        print(f"-- dry run: {n:,} instrukcji", file=sys.stderr)
        return n

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("replay-oltp wymaga pakietu psycopg: uv sync --extra postgres") from exc
    if not dsn:
        raise SystemExit("Podaj --dsn, np. postgresql://user:pass@localhost:5432/novacart")

    applied = 0
    with psycopg.connect(dsn) as conn:
        if init_schema:
            conn.execute(ddl())
            conn.commit()
            print("Utworzono schemat", file=sys.stderr)
        if not skip_snapshot:
            with conn.cursor() as cur:
                for _table, group in groupby(snapshot(root), key=lambda e: e["source"]["table"]):
                    rows = list(group)
                    sql, _ = statement(rows[0])
                    cur.executemany(sql, [statement(e)[1] for e in rows])
                    applied += len(rows)
            conn.commit()
            print(f"Załadowano migawkę: {applied:,} wierszy", file=sys.stderr)

        wall0 = time.monotonic()
        sim0: int | None = None
        last_report = time.monotonic()
        for _tx, group in groupby(changes(root, until), key=lambda e: e["source"]["txId"]):
            events = list(group)
            t_ms = events[0]["source"]["ts_ms"]
            if sim0 is None:
                sim0 = t_ms
            if speed > 0:
                delay = (t_ms - sim0) / 1000 / speed - (time.monotonic() - wall0)
                if delay > 0:
                    time.sleep(delay)
            with conn.transaction(), conn.cursor() as cur:
                for e in events:
                    cur.execute(*statement(e))
            applied += len(events)
            if time.monotonic() - last_report > 5:
                print(
                    f"  zastosowano {applied:,} zmian (czas symulacji: {events[0]['after'].get('updated_at', '')})",
                    file=sys.stderr,
                )
                last_report = time.monotonic()
    print(f"Gotowe: {applied:,} zmian", file=sys.stderr)
    return applied
