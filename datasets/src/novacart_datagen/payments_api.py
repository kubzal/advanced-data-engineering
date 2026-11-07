"""Mock API bramki płatności NovaCart (moduły 26 i 36: ingest z API).

Zachowuje się jak typowe API płatności:

* uwierzytelnianie ``Authorization: Bearer <token>`` (401 bez tokenu),
* paginacja kursorem (``limit``, ``starting_after`` jako nieprzezroczysty ``next_cursor``),
* filtrowanie po czasie (``created_gte``, ``created_lt``; ISO 8601 lub sekundy od epoki),
* kwoty w jednostkach podrzędnych (grosze/centy) jako liczby całkowite, waluta małymi literami,
* rate limiting (token bucket na token; 429 z nagłówkiem ``Retry-After``),
* losowe błędy 500/503 i opóźnienia (``--error-rate``, ``--latency-ms``) do ćwiczenia retry.

Endpointy: ``GET /v1/payments``, ``GET /v1/payments/{id}``, ``GET /health``.
"""

from __future__ import annotations

import base64
import json
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np
import pyarrow as pa

from .config import Config
from .orders import payments_table
from .world import World


@dataclass
class ApiOptions:
    host: str = "127.0.0.1"
    port: int = 8080
    token: str = "novacart-dev-token"
    rate_limit: float = 5.0  # żądań na sekundę
    burst: int = 10
    error_rate: float = 0.02
    latency_ms: int = 50
    max_limit: int = 500
    verbose: bool = False
    seed: int = 7


class PaymentsStore:
    """Wszystkie płatności z okresu, posortowane po (created_at, payment_id)."""

    def __init__(self, cfg: Config):
        world = World(cfg)
        tables = [payments_table(world, world.orders_for_day(d)) for d in range(cfg.days)]
        table = pa.concat_tables(tables).sort_by([("created_at", "ascending"), ("payment_id", "ascending")])
        self.created_us = table.column("created_at").cast(pa.int64()).to_numpy()
        self.rows = table.to_pylist()
        self.by_id = {r["payment_id"]: i for i, r in enumerate(self.rows)}

    def __len__(self) -> int:
        return len(self.rows)

    @staticmethod
    def to_api(r: dict[str, Any]) -> dict[str, Any]:
        method: dict[str, Any] = {"type": r["method"]}
        if r["card_brand"]:
            method["card"] = {"brand": r["card_brand"], "last4": r["card_last4"]}
        return {
            "id": r["payment_id"],
            "object": "refund" if r["type"] == "refund" else "charge",
            "created": int(r["created_at"].timestamp()),
            "amount": int(r["amount"] * 100),
            "currency": r["currency"].lower(),
            "status": r["status"],
            "failure_code": r["failure_code"],
            "payment_method": method,
            "customer": {"id": f"cus_{r['customer_id']:08d}", "email": r["payer_email"]},
            "metadata": {"order_id": str(r["order_id"])},
            "livemode": False,
        }

    def page(self, gte_us: int | None, lt_us: int | None, cursor: str | None, limit: int) -> dict[str, Any]:
        lo = 0 if gte_us is None else int(np.searchsorted(self.created_us, gte_us, side="left"))
        hi = len(self.rows) if lt_us is None else int(np.searchsorted(self.created_us, lt_us, side="left"))
        if cursor:
            after = self.by_id.get(_decode_cursor(cursor))
            if after is None:
                raise ValueError("invalid cursor")
            lo = max(lo, after + 1)
        items = self.rows[lo : min(hi, lo + limit)]
        has_more = lo + limit < hi
        return {
            "object": "list",
            "data": [self.to_api(r) for r in items],
            "has_more": has_more,
            "next_cursor": _encode_cursor(items[-1]["payment_id"]) if has_more and items else None,
        }


def _encode_cursor(payment_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"after": payment_id}).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> str:
    padded = cursor + "=" * (-len(cursor) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["after"]


def _parse_time(value: str) -> int:
    if value.isdigit():
        return int(value) * 1_000_000
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1_000_000)


@dataclass
class TokenBucket:
    rate: float
    capacity: int
    tokens: float = 0.0
    updated: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)

    def take(self) -> float:
        """Zwraca 0, jeśli żądanie może przejść, albo liczbę sekund do odczekania."""
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / self.rate


def make_server(store: PaymentsStore, opts: ApiOptions) -> ThreadingHTTPServer:
    buckets: dict[str, TokenBucket] = {}
    lock = threading.Lock()
    rnd = random.Random(opts.seed)

    class Handler(BaseHTTPRequestHandler):
        server_version = "NovaCartPayments/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            if opts.verbose:
                sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

        def _send(self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _error(
            self, status: int, type_: str, message: str, headers: dict[str, str] | None = None
        ) -> None:
            self._send(status, {"error": {"type": type_, "message": message}}, headers)

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/health":
                self._send(200, {"status": "ok", "payments": len(store)})
                return
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {opts.token}":
                self._error(
                    401, "authentication_error", "Brak lub niepoprawny token (Authorization: Bearer ...)"
                )
                return
            with lock:
                bucket = buckets.setdefault(auth, TokenBucket(opts.rate_limit, opts.burst))
                wait = bucket.take()
                fail = rnd.random() < opts.error_rate
                jitter = rnd.random()
            if wait > 0:
                self._error(
                    429, "rate_limit_error", "Za dużo żądań", {"Retry-After": str(max(1, int(wait + 0.999)))}
                )
                return
            time.sleep(opts.latency_ms / 1000 * (0.5 + jitter))
            if fail:
                self._error(
                    503 if jitter < 0.5 else 500, "api_error", "Chwilowy błąd serwera, spróbuj ponownie"
                )
                return
            if url.path == "/v1/payments":
                q = {k: v[-1] for k, v in parse_qs(url.query).items()}
                try:
                    limit = int(q.get("limit", 100))
                    if not 1 <= limit <= opts.max_limit:
                        raise ValueError(f"limit musi być w przedziale 1..{opts.max_limit}")
                    page = store.page(
                        _parse_time(q["created_gte"]) if "created_gte" in q else None,
                        _parse_time(q["created_lt"]) if "created_lt" in q else None,
                        q.get("starting_after"),
                        limit,
                    )
                except (ValueError, KeyError) as exc:
                    self._error(400, "invalid_request_error", str(exc))
                    return
                self._send(200, page)
                return
            if url.path.startswith("/v1/payments/"):
                pid = url.path.rsplit("/", 1)[-1]
                idx = store.by_id.get(pid)
                if idx is None:
                    self._error(404, "invalid_request_error", f"Nie znaleziono płatności {pid}")
                    return
                self._send(200, store.to_api(store.rows[idx]))
                return
            self._error(404, "invalid_request_error", "Nieznany endpoint")

    return ThreadingHTTPServer((opts.host, opts.port), Handler)


def serve(cfg: Config, opts: ApiOptions) -> None:
    print(f"Ładowanie płatności (skala {cfg.scale})...", file=sys.stderr)
    store = PaymentsStore(cfg)
    server = make_server(store, opts)
    host, port = server.server_address[:2]
    print(
        f"API płatności NovaCart: http://{host}:{port}  ({len(store):,} płatności)\n"
        f"  token: {opts.token}\n"
        f"  przykład: curl -H 'Authorization: Bearer {opts.token}' "
        f"'http://{host}:{port}/v1/payments?limit=2'",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
