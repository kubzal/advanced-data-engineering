"""Tryb strumieniowy: odtwarzanie clickstreamu w czasie rzeczywistym (lub przyspieszonym).

Generator bierze zdarzenia przyjęte danego dnia (łącznie ze spóźnionymi z dni poprzednich),
mapuje oś czasu na „teraz” i wysyła je w kolejności przyjęcia. Zdarzenia spóźnione docierają
ze starym ``event_ts``, duplikaty mają ten sam ``event_id``, tak jak w prawdziwym systemie.

Przy ``--speed N`` czas płynie N razy szybciej. Proporcjonalnie skracają się też opóźnienia:
zdarzenie spóźnione o 2 h przy ``--speed 60`` dotrze 2 minuty po swoim ``event_ts``.

Pole ``received_at`` nie jest wysyłane, bo ustawia je odbiorca (np. ``publish_time`` w Pub/Sub).
W zamian każde zdarzenie ma ``sent_at``, czyli moment wysłania przez generator.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import numpy as np
import pyarrow as pa

from .arrays import US_PER_DAY
from .clickstream import generate_clickstream
from .config import Config
from .world import World
from .writers import json_default

LATE_LOOKBACK_DAYS = 3


def _now_us() -> int:
    return time.time_ns() // 1000


def _iso(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def received_on_day(world: World, day: int) -> pa.Table:
    """Wszystkie zdarzenia przyjęte w dniu ``day``, posortowane po ``received_at``."""
    lo = world.day_start_us(day)
    hi = lo + US_PER_DAY
    parts = []
    # +1 dzień: sesje zamówień złożonych tuż po północy zaczynają się poprzedniego dnia
    for d in range(max(0, day - LATE_LOOKBACK_DAYS), min(day + 2, world.cfg.days)):
        t = generate_clickstream(world, d)
        r = t.column("received_at").cast(pa.int64()).to_numpy()
        a, b = np.searchsorted(r, [lo, hi])
        if b > a:
            parts.append(t.slice(int(a), int(b - a)))
    table = pa.concat_tables(parts)
    return table.sort_by("received_at")


class EventSink(Protocol):
    def send(self, event: dict[str, Any], payload: bytes) -> None: ...
    def close(self) -> None: ...


class StdoutSink:
    def send(self, event: dict[str, Any], payload: bytes) -> None:
        sys.stdout.write(payload.decode() + "\n")

    def close(self) -> None:
        sys.stdout.flush()


class FileSink:
    def __init__(self, path: str):
        self.f = open(path, "ab")  # noqa: SIM115

    def send(self, event: dict[str, Any], payload: bytes) -> None:
        self.f.write(payload + b"\n")

    def close(self) -> None:
        self.f.close()


class PubSubSink:
    """Publikacja do Pub/Sub z batchingiem; opcjonalnie z ordering keys (= session_id)."""

    def __init__(self, project: str, topic: str, ordering: bool = False):
        try:
            from google.cloud import pubsub_v1
        except ImportError as exc:
            raise SystemExit(
                "Sink pubsub wymaga pakietu google-cloud-pubsub: uv sync --extra pubsub"
            ) from exc
        self.client = pubsub_v1.PublisherClient(
            batch_settings=pubsub_v1.types.BatchSettings(max_messages=500, max_latency=0.05),
            publisher_options=pubsub_v1.types.PublisherOptions(enable_message_ordering=ordering),
        )
        self.topic = self.client.topic_path(project, topic)
        self.ordering = ordering
        self.futures: list[Any] = []

    def send(self, event: dict[str, Any], payload: bytes) -> None:
        kwargs: dict[str, str] = {
            "event_type": str(event.get("event_type")),
            "platform": str(event.get("platform")),
        }
        if self.ordering and event.get("session_id"):
            kwargs["ordering_key"] = event["session_id"]
        self.futures.append(self.client.publish(self.topic, payload, **kwargs))
        if len(self.futures) >= 5_000:
            self._drain()

    def _drain(self) -> None:
        for f in self.futures:
            f.result(timeout=60)
        self.futures.clear()

    def close(self) -> None:
        self._drain()


class KafkaSink:
    """Producent Kafki z idempotencją; kluczem jest session_id (zdarzenia sesji w jednej partycji)."""

    def __init__(self, bootstrap: str, topic: str):
        try:
            from confluent_kafka import Producer
        except ImportError as exc:
            raise SystemExit("Sink kafka wymaga pakietu confluent-kafka: uv sync --extra kafka") from exc
        self.producer = Producer(
            {
                "bootstrap.servers": bootstrap,
                "enable.idempotence": True,
                "linger.ms": 20,
                "compression.type": "zstd",
            }
        )
        self.topic = topic

    def send(self, event: dict[str, Any], payload: bytes) -> None:
        key = (event.get("session_id") or "").encode()
        while True:
            try:
                self.producer.produce(self.topic, value=payload, key=key)
                break
            except BufferError:
                self.producer.poll(0.1)
        self.producer.poll(0)

    def close(self) -> None:
        self.producer.flush(30)


@dataclass
class StreamOptions:
    start_day: int | None = None  # domyślnie ostatni dzień okresu
    speed: float = 1.0  # 0 = najszybciej jak się da
    rate: float | None = None  # docelowa średnia liczba zdarzeń na sekundę (nadpisuje speed)
    max_events: int | None = None
    duration_s: float | None = None
    align_time_of_day: bool = True  # zacznij od bieżącej godziny dnia (realistyczny wolumen)


def iter_events(world: World, opts: StreamOptions) -> Iterator[tuple[int, dict[str, Any]]]:
    """Zdarzenia (oryginalny received_at w µs, rekord) z kolejnych dni, w pętli."""
    day = opts.start_day if opts.start_day is not None else world.cfg.days - 1
    first = True
    while True:
        table = received_on_day(world, day)
        received = table.column("received_at").cast(pa.int64()).to_numpy()
        start = 0
        if first and opts.align_time_of_day:
            tod = _now_us() % US_PER_DAY
            start = int(np.searchsorted(received, world.day_start_us(day) + tod))
        first = False
        for batch in table.slice(start).to_batches(max_chunksize=10_000):
            r = batch.column("received_at").cast(pa.int64()).to_numpy()
            for us, row in zip(r, batch.to_pylist()):
                yield int(us), row
        day = day + 1 if day + 1 < world.cfg.days else min(LATE_LOOKBACK_DAYS, world.cfg.days - 1)


def run_stream(cfg: Config, sink: EventSink, opts: StreamOptions) -> int:
    world = World(cfg)
    speed = opts.speed
    if opts.rate:
        day = opts.start_day if opts.start_day is not None else cfg.days - 1
        per_day = received_on_day(world, day).num_rows
        speed = opts.rate * 86_400 / max(per_day, 1)
        print(f"Docelowo {opts.rate:.0f} zdarzeń/s → przyspieszenie czasu x{speed:.2f}", file=sys.stderr)
    wall0 = _now_us()
    sim0: int | None = None
    sent = 0
    try:
        for received_us, row in iter_events(world, opts):
            if sim0 is None:
                sim0 = received_us
            if speed > 0:
                delay = (wall0 + (received_us - sim0) / speed - _now_us()) / 1e6
                if delay > 0:
                    time.sleep(delay)
            event_us = int(row["event_ts"].timestamp() * 1e6)
            # oś czasu symulacji → oś czasu rzeczywistego; przy speed=0 (wysyłka hurtowa)
            # zostawiamy historyczne znaczniki czasu
            mapped = wall0 + (event_us - sim0) / speed if speed > 0 else event_us
            row["event_ts"] = _iso(int(mapped))
            row.pop("received_at", None)
            row["sent_at"] = _iso(_now_us())
            payload = json.dumps(row, default=json_default, ensure_ascii=False).encode("utf-8")
            sink.send(row, payload)
            sent += 1
            if opts.max_events and sent >= opts.max_events:
                break
            if opts.duration_s and (_now_us() - wall0) / 1e6 >= opts.duration_s:
                break
    except KeyboardInterrupt:
        pass
    finally:
        sink.close()
    print(f"Wysłano {sent:,} zdarzeń", file=sys.stderr)
    return sent
