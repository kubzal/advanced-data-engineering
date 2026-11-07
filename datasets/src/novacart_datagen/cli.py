"""Interfejs wiersza poleceń: ``novacart <polecenie> [opcje]``."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .config import ALL_COMPONENTS, DEFAULT_COMPONENTS, SCALES, Config
from .writers import FORMATS, is_empty_destination


def _add_world_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("świat NovaCart")
    g.add_argument("--scale", choices=list(SCALES), default="s", help="Preset skali (domyślnie: s)")
    g.add_argument("--seed", type=int, default=42, help="Ziarno losowości; ten sam seed = te same dane")
    g.add_argument("--start-date", type=date.fromisoformat, help="Początek okresu (YYYY-MM-DD)")
    g.add_argument("--end-date", type=date.fromisoformat, help="Koniec okresu (domyślnie 2025-12-31)")
    g.add_argument("--days", type=int, help="Długość okresu w dniach (nadpisuje preset)")
    g.add_argument("--customers", type=int, help="Liczba klientów (nadpisuje preset)")
    g.add_argument("--products", type=int, help="Liczba produktów (nadpisuje preset)")
    g.add_argument("--sellers", type=int, help="Liczba sprzedawców (nadpisuje preset)")
    g.add_argument("--orders-per-day", type=int, help="Bazowa liczba zamówień dziennie (nadpisuje preset)")
    q = p.add_argument_group("zachowanie i jakość danych")
    q.add_argument("--conversion-rate", type=float, help="Odsetek sesji z zakupem (domyślnie 0.05)")
    q.add_argument(
        "--skew", type=float, help="Skośność popularności produktów, wykładnik Zipfa (domyślnie 1.1)"
    )
    q.add_argument("--duplicate-rate", type=float, help="Odsetek zduplikowanych zdarzeń (domyślnie 0.01)")
    q.add_argument("--late-rate", type=float, help="Odsetek spóźnionych sesji mobilnych (domyślnie 0.03)")
    q.add_argument("--max-lateness-hours", type=float, help="Maksymalne opóźnienie zdarzenia (domyślnie 72)")
    q.add_argument("--clock-skew-rate", type=float, help="Odsetek sesji z błędnym zegarem (domyślnie 0.005)")
    q.add_argument("--invalid-rate", type=float, help="Odsetek uszkodzonych rekordów (domyślnie 0.002)")
    q.add_argument("--no-anomalies", action="store_true", help="Nie wstrzykuj anomalii")
    q.add_argument(
        "--clean", action="store_true", help="Dane „idealne”: bez duplikatów, opóźnień, uszkodzeń i anomalii"
    )


def _config(args: argparse.Namespace) -> Config:
    overrides = {
        k: getattr(args, k)
        for k in (
            "seed",
            "days",
            "customers",
            "products",
            "sellers",
            "orders_per_day",
            "conversion_rate",
            "skew",
            "duplicate_rate",
            "late_rate",
            "max_lateness_hours",
            "clock_skew_rate",
            "invalid_rate",
        )
    }
    if args.no_anomalies or args.clean:
        overrides["anomalies"] = False
    if args.clean:
        overrides.update(duplicate_rate=0.0, late_rate=0.0, clock_skew_rate=0.0, invalid_rate=0.0)
    return Config.from_scale(args.scale, start_date=args.start_date, end_date=args.end_date, **overrides)


def cmd_generate(args: argparse.Namespace) -> int:
    from .generate import run_generate

    cfg = _config(args)
    comps = (
        ALL_COMPONENTS if args.components == "all" else tuple(c.strip() for c in args.components.split(","))
    )
    unknown = set(comps) - set(ALL_COMPONENTS)
    if unknown:
        print(
            f"Nieznane komponenty: {', '.join(sorted(unknown))}. Dostępne: {', '.join(ALL_COMPONENTS)}",
            file=sys.stderr,
        )
        return 2
    if not args.overwrite and not is_empty_destination(args.output):
        print(
            f"Katalog {args.output} nie jest pusty. Użyj --overwrite albo wskaż inny katalog.",
            file=sys.stderr,
        )
        return 2
    run_generate(cfg, args.output, comps, args.format, args.compression, args.workers)
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    from .world import World

    print(
        f"{'skala':5} {'dni':>5} {'klienci':>11} {'produkty':>10} {'zamówienia':>12} {'zdarzenia~':>14}  opis"
    )
    for name, preset in SCALES.items():
        if args.scale and name != args.scale:
            continue
        cfg = Config.from_scale(
            name, customers=min(preset.customers, 1000), products=min(preset.products, 500)
        )
        orders = int(World(cfg).day_orders.sum())
        sessions = orders / cfg.conversion_rate
        events = int(orders * 8.5 + (sessions - orders) * 3.6)
        print(
            f"{name:5} {preset.days:>5} {preset.customers:>11,} {preset.products:>10,} {orders:>12,} "
            f"{events:>14,}  {preset.description}"
        )
    print(
        "\nRozmiary orientacyjne (Parquet/zstd): ~55 B na zdarzenie clickstream, ~80 B na zamówienie (skala M: ~3 GB, L: ~45 GB, XL: ~500 GB)."
    )
    return 0


def cmd_schemas(args: argparse.Namespace) -> int:
    from .replay import ddl
    from .schemas import export_schemas

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if args.format == "postgres":
        (out / "postgres_oltp.sql").write_text(ddl(), encoding="utf-8")
        print(out / "postgres_oltp.sql")
        return 0
    for fname, content in export_schemas(args.format).items():
        (out / fname).write_text(content + "\n", encoding="utf-8")
        print(out / fname)
    return 0


def cmd_stream(args: argparse.Namespace) -> int:
    from .stream import FileSink, KafkaSink, PubSubSink, StdoutSink, StreamOptions, run_stream

    cfg = _config(args)
    if args.sink == "stdout":
        sink = StdoutSink()
    elif args.sink == "file":
        if not args.path:
            raise SystemExit("--sink file wymaga --path")
        sink = FileSink(args.path)
    elif args.sink == "pubsub":
        project = args.project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project or not args.topic:
            raise SystemExit("--sink pubsub wymaga --project (lub GOOGLE_CLOUD_PROJECT) oraz --topic")
        sink = PubSubSink(project, args.topic, ordering=args.ordering)
    else:
        if not args.topic:
            raise SystemExit("--sink kafka wymaga --topic")
        sink = KafkaSink(args.bootstrap_servers, args.topic)
    opts = StreamOptions(
        start_day=args.start_day,
        speed=args.speed,
        rate=args.rate,
        max_events=args.max_events,
        duration_s=args.duration,
        align_time_of_day=not args.from_midnight,
    )
    run_stream(cfg, sink, opts)
    return 0


def cmd_payments_api(args: argparse.Namespace) -> int:
    from .payments_api import ApiOptions, serve

    cfg = _config(args)
    serve(
        cfg,
        ApiOptions(
            host=args.host,
            port=args.port,
            token=args.token,
            rate_limit=args.rate_limit,
            burst=args.burst,
            error_rate=args.error_rate,
            latency_ms=args.latency_ms,
            verbose=args.verbose,
        ),
    )
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    from .replay import run_replay

    root = args.cdc_dir.rstrip("/")
    run_replay(
        root,
        args.dsn,
        init_schema=args.init_schema,
        speed=args.speed,
        until=args.until,
        dry_run=args.dry_run,
        skip_snapshot=args.skip_snapshot,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novacart",
        description="Generator syntetycznych danych NovaCart (kurs Advanced Data Engineering).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Generuje zbiory danych do katalogu lub gs://bucket/prefiks")
    _add_world_args(g)
    g.add_argument("--output", "-o", required=True, help="Katalog docelowy lub gs://bucket/prefiks")
    g.add_argument(
        "--components",
        default=",".join(DEFAULT_COMPONENTS),
        help=f"Lista komponentów lub 'all'. Dostępne: {', '.join(ALL_COMPONENTS)} "
        f"(domyślnie: {','.join(DEFAULT_COMPONENTS)})",
    )
    g.add_argument("--format", choices=FORMATS, default="parquet", help="Format tabel (domyślnie parquet)")
    g.add_argument("--compression", help="Kompresja: dla parquet zstd|snappy|gzip|none, dla csv/jsonl gzip")
    g.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1), help="Liczba procesów")
    g.add_argument("--overwrite", action="store_true", help="Pozwól pisać do niepustego katalogu")
    g.set_defaults(func=cmd_generate)

    i = sub.add_parser("info", help="Pokazuje presety skali i szacowane wolumeny")
    i.add_argument("--scale", choices=list(SCALES))
    i.set_defaults(func=cmd_info)

    s = sub.add_parser("schemas", help="Eksportuje schematy (BigQuery JSON, Avro, Arrow, DDL PostgreSQL)")
    s.add_argument("--format", choices=("bigquery", "avro", "arrow", "postgres"), default="bigquery")
    s.add_argument("--output", "-o", default="schemas")
    s.set_defaults(func=cmd_schemas)

    st = sub.add_parser(
        "stream", help="Wysyła clickstream w czasie rzeczywistym (stdout, plik, Pub/Sub, Kafka)"
    )
    _add_world_args(st)
    st.add_argument("--sink", choices=("stdout", "file", "pubsub", "kafka"), default="stdout")
    st.add_argument("--path", help="Plik wyjściowy dla --sink file (JSON Lines, dopisywanie)")
    st.add_argument("--project", help="Projekt GCP dla --sink pubsub")
    st.add_argument("--topic", help="Temat Pub/Sub lub Kafka")
    st.add_argument("--ordering", action="store_true", help="Pub/Sub: ordering key = session_id")
    st.add_argument("--bootstrap-servers", default="localhost:9092", help="Kafka bootstrap servers")
    st.add_argument("--speed", type=float, default=1.0, help="Przyspieszenie czasu (0 = bez czekania)")
    st.add_argument("--rate", type=float, help="Docelowa średnia liczba zdarzeń/s (wylicza --speed)")
    st.add_argument("--start-day", type=int, help="Indeks dnia okresu, od którego zacząć (domyślnie ostatni)")
    st.add_argument(
        "--from-midnight", action="store_true", help="Zacznij od północy zamiast od bieżącej godziny"
    )
    st.add_argument("--max-events", type=int, help="Zakończ po N zdarzeniach")
    st.add_argument("--duration", type=float, help="Zakończ po N sekundach")
    st.set_defaults(func=cmd_stream)

    a = sub.add_parser("payments-api", help="Uruchamia mock API bramki płatności")
    _add_world_args(a)
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=8080)
    a.add_argument("--token", default="novacart-dev-token")
    a.add_argument("--rate-limit", type=float, default=5.0, help="Żądań na sekundę na token")
    a.add_argument("--burst", type=int, default=10, help="Maksymalny „zapas” żądań")
    a.add_argument("--error-rate", type=float, default=0.02, help="Odsetek losowych błędów 500/503")
    a.add_argument("--latency-ms", type=int, default=50, help="Średnie opóźnienie odpowiedzi")
    a.add_argument("--verbose", action="store_true")
    a.set_defaults(func=cmd_payments_api)

    r = sub.add_parser("replay-oltp", help="Odtwarza strumień CDC na bazie PostgreSQL (źródło dla CDC)")
    r.add_argument("--cdc-dir", required=True, help="Katalog cdc/ z wyniku generate --components cdc")
    r.add_argument("--dsn", help="postgresql://user:pass@host:5432/novacart")
    r.add_argument("--init-schema", action="store_true", help="Utwórz tabele przed załadowaniem")
    r.add_argument("--skip-snapshot", action="store_true", help="Pomiń ładowanie migawki początkowej")
    r.add_argument(
        "--speed", type=float, default=0.0, help="Przyspieszenie czasu (0 = najszybciej jak się da)"
    )
    r.add_argument("--until", help="Zakończ po tym dniu (YYYY-MM-DD)")
    r.add_argument("--dry-run", action="store_true", help="Tylko wypisz instrukcje SQL")
    r.set_defaults(func=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
