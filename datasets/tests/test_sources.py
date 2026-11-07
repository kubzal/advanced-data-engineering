"""Testy źródeł „surowych”: CDC, pliki przewoźników, mock API, stream, schematy."""

from __future__ import annotations

import csv
import gzip
import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pyarrow.dataset as ds
import pytest

from novacart_datagen.cdc import _py
from novacart_datagen.config import Config
from novacart_datagen.payments_api import ApiOptions, PaymentsStore, make_server
from novacart_datagen.replay import apply_to_memory, changes, run_replay, snapshot, statement
from novacart_datagen.schemas import SCHEMAS, export_schemas
from novacart_datagen.stream import StreamOptions, run_stream
from novacart_datagen.world import World


def _table_rows(root: Path, name: str, key: str) -> dict:
    t = ds.dataset(root / name, format="parquet", partitioning="hive").to_table()
    t = t.select([c for c in t.column_names if c != "dt"])
    return {r[key]: {k: _py(v) for k, v in r.items()} for r in t.to_pylist()}


def test_cdc_replay_reconstructs_final_state(dataset: Path) -> None:
    """Migawka + wszystkie zmiany CDC = eksport tabel na koniec okresu."""
    state = apply_to_memory(snapshot(str(dataset / "cdc")))
    state = apply_to_memory(changes(str(dataset / "cdc")), state)

    for table, key in (
        ("customers", "customer_id"),
        ("products", "product_id"),
        ("orders", "order_id"),
        ("sellers", "seller_id"),
    ):
        expected = _table_rows(dataset, table, key)
        actual = {k[0]: v for k, v in state[table].items()}
        assert actual.keys() == expected.keys(), table
        mismatched = [k for k in expected if actual[k] != expected[k]]
        assert not mismatched, f"{table}: {len(mismatched)} różnic, np. {mismatched[:3]}"

    items = ds.dataset(dataset / "order_items", format="parquet", partitioning="hive").to_table()
    assert len(state["order_items"]) == items.num_rows


def test_cdc_events_ordered_and_transactional(dataset: Path) -> None:
    events = list(changes(str(dataset / "cdc")))
    lsns = [e["source"]["lsn"] for e in events]
    assert lsns == sorted(lsns)
    creates = [e for e in events if e["source"]["table"] == "orders" and e["op"] == "c"]
    tx = creates[0]["source"]["txId"]
    items = [e for e in events if e["source"]["table"] == "order_items" and e["source"]["txId"] == tx]
    assert len(items) == creates[0]["after"]["items_count"]
    updates = [e for e in events if e["op"] == "u" and e["source"]["table"] == "orders"]
    assert all(u["before"]["status"] != u["after"]["status"] for u in updates)


def test_replay_statements(dataset: Path, capsys: pytest.CaptureFixture) -> None:
    ev = next(e for e in changes(str(dataset / "cdc")) if e["op"] == "u" and e["source"]["table"] == "orders")
    sql, params = statement(ev)
    assert sql.startswith("UPDATE orders SET") and sql.endswith("WHERE order_id = %s")
    assert params[-1] == ev["after"]["order_id"]
    n = run_replay(str(dataset / "cdc"), None, dry_run=True)
    assert n > 0
    assert "INSERT INTO categories" in capsys.readouterr().out


def test_partner_files(dataset: Path, world: World) -> None:
    sp = sorted((dataset / "partners" / "speedpost").rglob("*.csv"))
    missing = world.anomaly("partner_file_missing")
    assert not any(missing.date.replace("-", "") in p.name for p in sp)
    text = sp[0].read_bytes().decode("cp1250")
    header = next(csv.reader(io.StringIO(text), delimiter=";"))
    assert header[:3] == ["numer_przesylki", "referencja_zamowienia", "status"]

    qs = sorted((dataset / "partners" / "quickship").glob("*.csv"))
    headers = {p.read_text().splitlines()[0] for p in qs}
    assert len(headers) == 2, "QuickShip powinien zmienić schemat w trakcie okresu"

    ep = sorted((dataset / "partners" / "europarcel").rglob("*.jsonl.gz"))
    first = json.loads(gzip.decompress(ep[-1].read_bytes()).splitlines()[0])
    assert first["parcel"]["reference"].startswith("NC-")


def test_payments_api_pagination_auth_and_rate_limit(cfg: Config) -> None:
    store = PaymentsStore(cfg)
    opts = ApiOptions(port=0, rate_limit=1000, burst=1000, error_rate=0.0, latency_ms=0)
    server = make_server(store, opts)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def get(path: str, token: str | None = opts.token) -> tuple[int, dict]:
        req = urllib.request.Request(
            base + path, headers={"Authorization": f"Bearer {token}"} if token else {}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    try:
        assert get("/v1/payments", token=None)[0] == 401
        seen, cursor = [], None
        while True:
            status, page = get("/v1/payments?limit=500" + (f"&starting_after={cursor}" if cursor else ""))
            assert status == 200
            seen += [p["id"] for p in page["data"]]
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        assert len(seen) == len(set(seen)) == len(store)
        assert isinstance(page["data"][0]["amount"], int)
        status, one = get(f"/v1/payments/{seen[0]}")
        assert status == 200 and one["id"] == seen[0]
    finally:
        server.shutdown()

    limited = make_server(store, ApiOptions(port=0, rate_limit=0.1, burst=2, error_rate=0.0, latency_ms=0))
    t2 = threading.Thread(target=limited.serve_forever, daemon=True)
    t2.start()
    base = f"http://127.0.0.1:{limited.server_address[1]}"
    try:
        codes = [get("/v1/payments?limit=1")[0] for _ in range(4)]
        assert codes[:2] == [200, 200] and 429 in codes[2:]
    finally:
        limited.shutdown()


class _ListSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def send(self, event: dict, payload: bytes) -> None:
        self.events.append(json.loads(payload))

    def close(self) -> None:
        pass


def test_stream_emits_events_without_received_at(cfg: Config) -> None:
    sink = _ListSink()
    sent = run_stream(cfg, sink, StreamOptions(speed=0, max_events=500, align_time_of_day=False))
    assert sent == 500
    assert "received_at" not in sink.events[0] and "sent_at" in sink.events[0]


def test_schema_exports() -> None:
    bq = export_schemas("bigquery")
    assert set(bq) == {f"{n}.json" for n in SCHEMAS}
    orders = json.loads(bq["orders.json"])
    assert {f["name"]: f["type"] for f in orders}["total_amount"] == "NUMERIC"
    avro = json.loads(export_schemas("avro")["clickstream.avsc"])
    assert avro["type"] == "record"
