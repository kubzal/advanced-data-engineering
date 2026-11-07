# examples/05_pubsub_emulator_demo.py
"""Pub/Sub bez chmury: temat, subskrypcje, publikacja zdarzeń NovaCart i odbiór w emulatorze.

Uruchomienie (emulator z examples/compose/docker-compose.yml):

    docker compose -f compose/docker-compose.yml up -d pubsub
    export PUBSUB_EMULATOR_HOST=localhost:8085
    uv run python 05_pubsub_emulator_demo.py --events 2000

Skrypt odmawia działania bez PUBSUB_EMULATOR_HOST, żeby przypadkiem nie utworzyć zasobów
w prawdziwym projekcie GCP.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import duckdb
from google.api_core import exceptions as gexc
from google.cloud import pubsub_v1

PROJECT = "novacart-local"
TOPIC = "clickstream"
REPO_ROOT = Path(__file__).resolve().parents[3]


def data_root() -> Path:
    return Path(os.environ.get("NOVACART_DATA", REPO_ROOT / "data" / "xs"))


def load_events(n: int) -> list[dict]:
    """Pierwsze n zdarzeń z jednego dnia clickstreamu, w kolejności przyjęcia (received_at)."""
    glob = (data_root() / "clickstream" / "*" / "*.parquet").as_posix()
    rel = duckdb.sql(
        f"""
        SELECT event_id, event_type, CAST(event_ts AS VARCHAR) AS event_ts, session_id,
               platform, customer_id, product_id, order_id
        FROM read_parquet('{glob}', hive_partitioning = true)
        WHERE dt = (SELECT max(dt) FROM read_parquet('{glob}', hive_partitioning = true))
        ORDER BY received_at
        LIMIT {n}
        """
    )
    cols = rel.columns
    return [dict(zip(cols, row, strict=True)) for row in rel.fetchall()]


def ensure_topic(publisher: pubsub_v1.PublisherClient, topic_path: str) -> None:
    try:
        publisher.create_topic(request={"name": topic_path})
        print(f"utworzono temat         {topic_path}")
    except gexc.AlreadyExists:
        print(f"temat już istnieje      {topic_path}")


def ensure_subscription(
    subscriber: pubsub_v1.SubscriberClient, sub_path: str, topic_path: str, filter_: str = ""
) -> None:
    request = {
        "name": sub_path,
        "topic": topic_path,
        "ack_deadline_seconds": 30,
        "enable_message_ordering": True,
    }
    if filter_:
        request["filter"] = filter_
    try:
        subscriber.create_subscription(request=request)
        print(f"utworzono subskrypcję   {sub_path}" + (f"  (filtr: {filter_})" if filter_ else ""))
    except gexc.AlreadyExists:
        print(f"subskrypcja już istnieje {sub_path}")


def publish(publisher: pubsub_v1.PublisherClient, topic_path: str, events: list[dict]) -> float:
    started = time.perf_counter()
    futures = []
    for e in events:
        payload = json.dumps(e, separators=(",", ":")).encode()
        futures.append(
            publisher.publish(
                topic_path,
                payload,
                # klucz kolejności: zdarzenia jednej sesji trafią do subskrybenta w kolejności publikacji
                ordering_key=e["session_id"] or "",
                # atrybuty są widoczne bez parsowania treści, m.in. dla filtrów subskrypcji
                event_type=str(e["event_type"]),
                platform=str(e["platform"]),
            )
        )
    for f in futures:
        f.result(timeout=30)  # message_id nadany przez serwer = publikacja potwierdzona
    return time.perf_counter() - started


def drain(subscriber: pubsub_v1.SubscriberClient, sub_path: str) -> tuple[Counter, Counter, int]:
    """Synchroniczny pull aż do dwóch pustych odpowiedzi z rzędu."""
    by_type: Counter = Counter()
    seen_ids: Counter = Counter()
    received = empty = 0
    while empty < 2:
        try:
            resp = subscriber.pull(request={"subscription": sub_path, "max_messages": 500}, timeout=5)
        except gexc.DeadlineExceeded:
            resp = None
        if not resp or not resp.received_messages:
            empty += 1
            continue
        empty = 0
        ack_ids = []
        for rm in resp.received_messages:
            body = json.loads(rm.message.data)
            by_type[rm.message.attributes.get("event_type", "?")] += 1
            seen_ids[body["event_id"]] += 1
            ack_ids.append(rm.ack_id)
        subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})
        received += len(ack_ids)
    return by_type, seen_ids, received


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=int, default=2000)
    parser.add_argument("--keep", action="store_true", help="nie usuwaj tematu i subskrypcji na końcu")
    args = parser.parse_args()

    host = os.environ.get("PUBSUB_EMULATOR_HOST")
    if not host:
        print("Brak PUBSUB_EMULATOR_HOST. Ten przykład działa wyłącznie z emulatorem:", file=sys.stderr)
        print("  export PUBSUB_EMULATOR_HOST=localhost:8085", file=sys.stderr)
        return 2
    print(f"emulator: {host} (kanał gRPC bez TLS i bez uwierzytelniania)\n")

    events = load_events(args.events)
    publisher = pubsub_v1.PublisherClient(
        publisher_options=pubsub_v1.types.PublisherOptions(enable_message_ordering=True)
    )
    subscriber = pubsub_v1.SubscriberClient()
    topic_path = publisher.topic_path(PROJECT, TOPIC)
    sub_all = subscriber.subscription_path(PROJECT, "clickstream-all")
    sub_purchase = subscriber.subscription_path(PROJECT, "clickstream-purchases")

    ensure_topic(publisher, topic_path)
    ensure_subscription(subscriber, sub_all, topic_path)
    ensure_subscription(subscriber, sub_purchase, topic_path, 'attributes.event_type = "purchase"')

    elapsed = publish(publisher, topic_path, events)
    print(f"\nopublikowano {len(events)} zdarzeń w {elapsed:.2f} s ({len(events) / elapsed:,.0f} msg/s)")

    by_type, seen, received = drain(subscriber, sub_all)
    dup_ids = sum(1 for c in seen.values() if c > 1)
    print(f"\n[clickstream-all] odebrano {received} wiadomości, unikalnych event_id: {len(seen)}")
    print(f"  event_id występujące więcej niż raz: {dup_ids} (duplikaty z generatora, nie z Pub/Sub)")
    for event_type, n in by_type.most_common():
        print(f"  {event_type:<18} {n:>6}")

    by_type_p, _, received_p = drain(subscriber, sub_purchase)
    print(f"\n[clickstream-purchases] odebrano {received_p} wiadomości: {dict(by_type_p)}")

    if not args.keep:
        subscriber.delete_subscription(request={"subscription": sub_all})
        subscriber.delete_subscription(request={"subscription": sub_purchase})
        publisher.delete_topic(request={"topic": topic_path})
        print("\nusunięto temat i subskrypcje (użyj --keep, żeby je zostawić)")
    subscriber.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
