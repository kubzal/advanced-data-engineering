"""Zdarzenia śledzenia przesyłek i dzienne pliki od partnerów logistycznych.

Każdy przewoźnik ma inną „osobowość” formatu, celowo realistyczną i uciążliwą:

* **SpeedPost** — CSV z separatorem ``;``, kodowanie **Windows-1250**, przecinek dziesiętny,
  czas lokalny *bez strefy czasowej* (``DD.MM.YYYY HH:MM:SS``), polskie nazwy kolumn i statusów,
  ponowne wysyłanie części wierszy z poprzedniego dnia (duplikaty między plikami).
* **EuroParcel** — JSON Lines skompresowany gzip, zagnieżdżona struktura, czas UTC (ISO 8601 z ``Z``),
  referencja zamówienia w formacie ``NC-<order_id>``.
* **QuickShip** — CSV UTF-8, czas z przesunięciem strefy (``+01:00``), duplikaty w obrębie pliku
  i **nieogłoszona zmiana schematu** w trakcie okresu (zmiana nazwy kolumny, jednostki wagi, nowa kolumna).

Plik za dzień D zawiera zdarzenia z dnia D. Zdarzenie może dotyczyć zamówienia złożonego
do kilkunastu dni wcześniej, dlatego generator odtwarza zamówienia z okna kilkunastu dni wstecz
(deterministycznie, z cache).
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import numpy as np

from . import reference as ref
from .arrays import NULL_TS, US_PER_DAY, US_PER_HOUR, Stream, rng_for
from .orders import OrdersBatch
from .world import CITY_COUNTRY, CITY_POOL

if TYPE_CHECKING:
    from .world import World

TRACK_CODES = ("LABEL_CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "FAILED_DELIVERY", "DELIVERED")
SPEEDPOST_STATUS = (
    "NADANIE",
    "ODEBRANO_OD_NADAWCY",
    "W_TRANSPORCIE",
    "W_DORECZENIU",
    "NIEUDANE_DORECZENIE",
    "DORECZONO",
)
QUICKSHIP_STATUS = (
    "label_created",
    "picked_up",
    "in_transit",
    "out_for_delivery",
    "delivery_failed",
    "delivered",
)
LOOKBACK_DAYS = 25  # najdłuższa droga od zamówienia do ostatniego zdarzenia przewoźnika

HUB_NAMES: list[str] = []
HUB_COUNTRY: list[int] = []
HUB_RANGES: list[tuple[int, int]] = []
for _carrier in ref.CARRIERS:
    _start = len(CITY_POOL) + len(HUB_NAMES)
    for _name, _cc in ref.CARRIER_HUBS[_carrier]:
        HUB_NAMES.append(_name)
        HUB_COUNTRY.append(ref.COUNTRY_CODES.index(_cc))
    HUB_RANGES.append((_start, len(ref.CARRIER_HUBS[_carrier])))
LOCATION_POOL = CITY_POOL + HUB_NAMES
LOCATION_COUNTRY = np.array(CITY_COUNTRY + HUB_COUNTRY)


def tracking_events(world: World, batch: OrdersBatch) -> dict[str, np.ndarray]:
    """Wszystkie zdarzenia przewoźników dla zamówień z jednego dnia (pełny cykl, bez obcinania)."""
    rng = rng_for(world.cfg.seed, Stream.LOGISTICS, batch.day)
    rows = np.nonzero(batch.shipped != NULL_TS)[0]
    n = len(rows)
    shipped = batch.shipped[rows]
    delivered = batch.delivered[rows]
    c = world.customers
    cust = batch.customer[rows]
    moved = (c.move_us[cust] != NULL_TS) & (c.move_us[cust] <= batch.created[rows])
    dest = np.where(moved, c.city2[cust], c.city[cust])
    first_item = np.searchsorted(batch.item_row, np.arange(batch.n))
    origin = world.sellers.city[batch.item_seller[first_item][rows]]
    carrier = batch.carrier[rows]
    hub_start = np.array([s for s, _ in HUB_RANGES])[carrier]
    hub_len = np.array([ln for _, ln in HUB_RANGES])[carrier]
    hub1 = hub_start + rng.integers(0, hub_len)
    hub2 = hub_start + (hub1 - hub_start + 1 + rng.integers(0, hub_len - 1)) % hub_len
    cross_border = CITY_COUNTRY_ARR[origin] != CITY_COUNTRY_ARR[dest]
    failed = batch.failed_delivery[rows]
    span = delivered - shipped
    p = world.products
    weight_g = np.bincount(
        batch.item_row, weights=p.weight_g[batch.item_product] * batch.item_qty, minlength=batch.n
    )[rows].astype(np.int64)

    parts: list[tuple[np.ndarray, int, np.ndarray, np.ndarray]] = []  # (maska, kod, czas, lokalizacja)
    all_ = np.ones(n, dtype=bool)
    # etykieta powstaje przed odbiorem przez kuriera, ale nigdy przed złożeniem zamówienia
    label = np.maximum(
        shipped - rng.integers(US_PER_HOUR, 6 * US_PER_HOUR, n), batch.created[rows] + 10 * 60 * 1_000_000
    )
    parts.append((all_, 0, np.minimum(label, shipped - 1), origin))
    parts.append((all_, 1, shipped, origin))
    parts.append((all_, 2, shipped + (span * 0.35).astype(np.int64), hub1))
    parts.append((cross_border, 2, shipped + (span * 0.65).astype(np.int64), hub2))
    first_attempt = delivered - US_PER_DAY
    parts.append((failed, 3, first_attempt - rng.integers(US_PER_HOUR, 5 * US_PER_HOUR, n), dest))
    parts.append((failed, 4, first_attempt, dest))
    parts.append((all_, 3, delivered - rng.integers(US_PER_HOUR, 5 * US_PER_HOUR, n), dest))
    parts.append((all_, 5, delivered, dest))

    sel = [np.nonzero(m)[0] for m, *_ in parts]
    shipment_row = np.concatenate(sel)
    out = {
        "row": rows[shipment_row],
        "code": np.concatenate([np.full(len(s), code, np.int8) for s, (_, code, _, _) in zip(sel, parts)]),
        "ts": np.concatenate([t[s] for s, (_, _, t, _) in zip(sel, parts)]),
        "location": np.concatenate([loc[s] for s, (_, _, _, loc) in zip(sel, parts)]),
        "carrier": carrier[shipment_row],
        "weight_g": weight_g[shipment_row],
        "dest_city": dest[shipment_row],
        "express": (rng.random(n) < 0.15)[shipment_row],
    }
    order = np.lexsort((out["code"], out["ts"]))
    return {k: v[order] for k, v in out.items()}


CITY_COUNTRY_ARR = np.array(CITY_COUNTRY)


def _events_window(world: World, lo_us: int, hi_us: int) -> list[tuple[OrdersBatch, dict[str, np.ndarray]]]:
    """Zdarzenia z przedziału [lo_us, hi_us) dla wszystkich zamówień, które mogą je mieć."""
    first_day = max(0, int(world.day_of(lo_us)) - LOOKBACK_DAYS)
    last_day = min(world.cfg.days - 1, int(world.day_of(hi_us)))
    result = []
    for d in range(first_day, last_day + 1):
        batch = world.orders_for_day(d)
        ev = _cached_tracking(world, batch)
        mask = (ev["ts"] >= lo_us) & (ev["ts"] < hi_us) & (ev["ts"] <= world.end_us)
        if mask.any():
            result.append((batch, {k: v[mask] for k, v in ev.items()}))
    return result


_TRACKING_CACHE: dict[tuple[int, int, int], dict[str, np.ndarray]] = {}


def _cached_tracking(world: World, batch: OrdersBatch) -> dict[str, np.ndarray]:
    key = (id(world), batch.day, batch.n)
    if key not in _TRACKING_CACHE:
        if len(_TRACKING_CACHE) > 64:
            _TRACKING_CACHE.pop(next(iter(_TRACKING_CACHE)))
        _TRACKING_CACHE[key] = tracking_events(world, batch)
    return _TRACKING_CACHE[key]


def _utc_iso(us: np.ndarray) -> np.ndarray:
    return np.char.add(np.datetime_as_string(us.astype("datetime64[us]"), unit="s"), "Z")


def _offsets_us(us: np.ndarray, tz: str) -> np.ndarray:
    """Przesunięcie strefy czasowej (w µs) dla każdego znacznika; liczone raz na dzień."""
    zone = ZoneInfo(tz)
    days = us // US_PER_DAY
    out = np.empty(len(us), dtype=np.int64)
    for d in np.unique(days):
        noon = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(days=int(d), hours=12)
        out[days == d] = int(noon.astimezone(zone).utcoffset().total_seconds()) * 1_000_000  # type: ignore[union-attr]
    return out


def partner_files_for_date(world: World, day: int) -> list[tuple[str, bytes]]:
    """Pliki wszystkich przewoźników za dzień ``day`` (indeks dnia w okresie)."""
    d: date = world.dates[day]
    day_start = world.day_start_us(day)
    window = _events_window(world, day_start - 3 * US_PER_DAY, day_start + 2 * US_PER_DAY)
    files: list[tuple[str, bytes]] = []
    sp = _speedpost(world, day, window)
    if sp is not None:
        files.append((f"partners/speedpost/{d:%Y/%m/%d}/SP_TRACKING_{d:%Y%m%d}.csv", sp))
    files.append(
        (
            f"partners/europarcel/dt={d.isoformat()}/europarcel_events_{d.isoformat()}.jsonl.gz",
            _europarcel(world, day, window),
        )
    )
    files.append((f"partners/quickship/quickship_{d:%Y%m%d}.csv", _quickship(world, day, window)))
    return files


def _select(
    window: list[tuple[OrdersBatch, dict[str, np.ndarray]]],
    carrier: int,
    lo: int,
    hi: int,
    local_offset_tz: str | None = None,
) -> list[tuple[OrdersBatch, dict[str, np.ndarray]]]:
    out = []
    for batch, ev in window:
        t = ev["ts"] + (_offsets_us(ev["ts"], local_offset_tz) if local_offset_tz else 0)
        mask = (ev["carrier"] == carrier) & (t >= lo) & (t < hi)
        if mask.any():
            out.append((batch, {k: v[mask] for k, v in ev.items()}))
    return out


def _speedpost(world: World, day: int, window: list) -> bytes | None:
    missing = world.anomaly("partner_file_missing")
    if missing is not None and missing.day_index == day:
        return None
    rng = rng_for(world.cfg.seed, Stream.PARTNER_FILES, day, 0)
    day_start = world.day_start_us(day)
    lo = day_start
    if missing is not None and missing.day_index == day - 1:
        lo -= US_PER_DAY  # zaległy plik z poprzedniego dnia doklejony do bieżącego
    current = _select(window, 0, lo, day_start + US_PER_DAY, "Europe/Warsaw")
    previous = _select(window, 0, lo - US_PER_DAY, lo, "Europe/Warsaw")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(
        [
            "numer_przesylki",
            "referencja_zamowienia",
            "status",
            "data_zdarzenia",
            "miejscowosc",
            "kraj",
            "waga_kg",
            "odbiorca",
            "kod_pocztowy",
        ]
    )
    for chunk, resend in ((previous, True), (current, False)):
        for batch, ev in chunk:
            keep = rng.random(len(ev["ts"])) < 0.02 if resend else np.ones(len(ev["ts"]), bool)
            if not keep.any():
                continue
            ev = {k: v[keep] for k, v in ev.items()}
            local = ev["ts"] + _offsets_us(ev["ts"], "Europe/Warsaw")
            stamps = np.datetime_as_string(local.astype("datetime64[us]"), unit="s")
            rows = ev["row"]
            profile = world.customer_profile(batch.customer[rows], batch.created[rows])
            first = profile["first_name"].to_pylist()
            last = profile["last_name"].to_pylist()
            postal = profile["postal_code"].to_pylist()
            sid = batch.shipment_id.take(rows).to_pylist()
            for i in range(len(rows)):
                s = stamps[i]
                w.writerow(
                    [
                        sid[i],
                        str(batch.order_id[rows[i]]),
                        SPEEDPOST_STATUS[ev["code"][i]],
                        f"{s[8:10]}.{s[5:7]}.{s[0:4]} {s[11:19]}",
                        LOCATION_POOL[ev["location"][i]],
                        ref.COUNTRY_CODES[LOCATION_COUNTRY[ev["location"][i]]],
                        f"{ev['weight_g'][i] / 1000:.2f}".replace(".", ","),
                        f"{first[i] or ''} {last[i] or ''}".strip(),
                        postal[i] or "",
                    ]
                )
    return buf.getvalue().encode("cp1250", errors="replace")


def _europarcel(world: World, day: int, window: list) -> bytes:
    day_start = world.day_start_us(day)
    sent_at = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=day_start + US_PER_DAY + 2 * US_PER_HOUR
    )
    sent = sent_at.isoformat().replace("+00:00", "Z")
    lines = []
    for batch, ev in _select(window, 1, day_start, day_start + US_PER_DAY):
        stamps = _utc_iso(ev["ts"])
        sid = batch.shipment_id.take(ev["row"]).to_pylist()
        for i in range(len(stamps)):
            loc = int(ev["location"][i])
            lines.append(
                json.dumps(
                    {
                        "parcel": {"id": sid[i], "reference": f"NC-{batch.order_id[ev['row'][i]]}"},
                        "event": {
                            "code": TRACK_CODES[ev["code"][i]],
                            "timestamp": str(stamps[i]),
                            "location": {
                                "city": LOCATION_POOL[loc],
                                "country": ref.COUNTRY_CODES[LOCATION_COUNTRY[loc]],
                            },
                        },
                        "weight": {"value": round(float(ev["weight_g"][i]) / 1000, 3), "unit": "kg"},
                        "sent_at": sent,
                    },
                    ensure_ascii=False,
                )
            )
    return gzip.compress(("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"), mtime=0)


def _quickship(world: World, day: int, window: list) -> bytes:
    rng = rng_for(world.cfg.seed, Stream.PARTNER_FILES, day, 2)
    change = world.anomaly("partner_schema_change")
    v2 = change is not None and day >= change.day_index
    day_start = world.day_start_us(day)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if v2:
        w.writerow(
            [
                "tracking_number",
                "order_ref",
                "status",
                "event_time",
                "city",
                "country_code",
                "weight_kg",
                "service_level",
            ]
        )
    else:
        w.writerow(
            ["tracking_id", "order_ref", "status", "event_time", "city", "country_code", "weight_grams"]
        )
    for batch, ev in _select(window, 2, day_start, day_start + US_PER_DAY):
        offsets = _offsets_us(ev["ts"], "Europe/Berlin")
        stamps = np.datetime_as_string((ev["ts"] + offsets).astype("datetime64[us]"), unit="s")
        sid = batch.shipment_id.take(ev["row"]).to_pylist()
        dup = rng.random(len(stamps)) < 0.01
        for i in range(len(stamps)):
            off_h = offsets[i] // US_PER_HOUR
            loc = int(ev["location"][i])
            row = [
                sid[i],
                str(batch.order_id[ev["row"][i]]),
                QUICKSHIP_STATUS[ev["code"][i]],
                f"{stamps[i]}+{off_h:02d}:00",
                LOCATION_POOL[loc],
                ref.COUNTRY_CODES[LOCATION_COUNTRY[loc]],
            ]
            if v2:
                row += [f"{ev['weight_g'][i] / 1000:.3f}", "express" if ev["express"][i] else "standard"]
            else:
                row += [str(int(ev["weight_g"][i]))]
            w.writerow(row)
            if dup[i]:
                w.writerow(row)
    return buf.getvalue().encode("utf-8")


def tracking_table_rows(world: World, day: int) -> int:
    """Liczba zdarzeń śledzenia w danym dniu (używane w statystykach)."""
    day_start = world.day_start_us(day)
    return sum(len(ev["ts"]) for _, ev in _events_window(world, day_start, day_start + US_PER_DAY))
