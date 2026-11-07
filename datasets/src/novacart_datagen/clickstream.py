"""Clickstream: zdarzenia z aplikacji web i mobilnych.

Każde zamówienie z danego dnia ma „swoją” sesję zakończoną zdarzeniem ``purchase``
(z tym samym ``order_id`` i znacznikiem czasu), więc clickstream i zamówienia da się
złączyć. Pozostałe sesje to przeglądanie bez zakupu (współczynnik konwersji z konfiguracji).

Świadomie wprowadzane problemy (sterowane konfiguracją):

* **Opóźnienia** — sesje mobilne w trybie offline docierają z opóźnieniem do ``max_lateness_hours``.
* **Rozjechany zegar** — część urządzeń wysyła ``event_ts`` przesunięty o godziny (nawet w przyszłość).
* **Duplikaty** — ponowne wysłanie tego samego zdarzenia (to samo ``event_id``, późniejsze ``received_at``).
* **Uszkodzone rekordy** — literówki w ``event_type``, brak ``session_id``, ujemne ceny, nieistniejący klient.

Kolumna ``event_ts`` to czas zdarzenia według urządzenia (event time), a ``received_at`` to czas
przyjęcia przez kolektor (processing time). Dane wyjściowe są posortowane po ``received_at``,
tak jak zapisałby je system ingestu.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from . import reference as ref
from .arrays import (
    US_PER_HOUR,
    US_PER_MINUTE,
    US_PER_SECOND,
    Stream,
    hashed_uuid_strings,
    int_to_str,
    join,
    money,
    nullable,
    rng_for,
    sample_prefix,
    segment_positions,
    take_strings,
    ts,
    uuid4_strings,
    weighted_choice,
)
from .orders import OrdersBatch
from .world import COUNTRY_CURRENCY, LEAF_CATEGORY_ID, local_price_cents

if TYPE_CHECKING:
    from .world import World

EVENT_TYPES = (
    "page_view",
    "product_view",
    "search",
    "add_to_cart",
    "remove_from_cart",
    "add_to_wishlist",
    "view_cart",
    "begin_checkout",
    "purchase",
)
E = {name: i for i, name in enumerate(EVENT_TYPES)}
BROWSE_WEIGHTS = np.array([0.14, 0.45, 0.15, 0.09, 0.03, 0.05, 0.09, 0.0, 0.0])
INVALID_EVENT_TYPES = ("pageview", "Product_View", "add-to-cart", "")
PRODUCT_EVENTS = np.array([E["product_view"], E["add_to_cart"], E["remove_from_cart"], E["add_to_wishlist"]])
PRODUCT_LISTS = ("search", "category", "recommendation", "direct", "homepage")
APP_VERSION_EPOCH = date(2024, 1, 1)

_TERMS = [t for leaf in ref.LEAVES for t in leaf.leaf.search_terms]  # type: ignore[union-attr]


def _typo(term: str) -> str:
    if len(term) < 6:
        return term + term[-1]
    mid = len(term) // 2
    return term[:mid] + term[mid + 1 :]


SEARCH_POOL = _TERMS + [_typo(t) for t in _TERMS]
SEARCH_PATH_POOL = ["/szukaj?q=" + quote_plus(t) for t in SEARCH_POOL]
LEAF_PATHS = ["/c/" + c.slug for c in ref.LEAVES]
UA_POOL: list[tuple[str, str]] = []  # (część przed wersją, część po wersji)
UA_RANGES: list[tuple[int, int]] = []
for _platform in ref.PLATFORMS:
    _start = len(UA_POOL)
    for _ua in ref.USER_AGENTS[_platform]:
        before, _, after = _ua.partition("{v}")
        UA_POOL.append((before, after))
    UA_RANGES.append((_start, len(UA_POOL) - _start))


def _json_obj(*pairs: tuple[str, pa.Array, bool]) -> pa.Array:
    """Buduje napis JSON z kolumn (klucz, wartość, czy_napis) bez pętli w Pythonie."""
    parts: list[pa.Array | str] = ["{"]
    for i, (key, value, quoted) in enumerate(pairs):
        parts.append(("," if i else "") + f'"{key}":' + ('"' if quoted else ""))
        parts.append(value)
        if quoted:
            parts.append('"')
    parts.append("}")
    return join(*parts)


def generate_clickstream(world: World, day: int, batch: OrdersBatch | None = None) -> pa.Table:
    cfg = world.cfg
    rng = rng_for(cfg.seed, Stream.CLICKSTREAM, day)
    batch = batch if batch is not None else world.orders_for_day(day)
    c, p = world.customers, world.products
    day_start = world.day_start_us(day)

    # -- sesje --------------------------------------------------------------------------------
    n_conv = batch.n
    n_sess = max(n_conv + 1, int(round(n_conv / cfg.conversion_rate)))
    n_non = n_sess - n_conv
    S = n_sess
    is_conv = np.zeros(S, dtype=bool)
    is_conv[:n_conv] = True

    platform = np.empty(S, dtype=np.int64)
    platform[:n_conv] = batch.platform
    platform[n_conv:] = weighted_choice(rng, [0.60, 0.22, 0.18], n_non)

    cust = np.full(S, -1, dtype=np.int64)
    cust[:n_conv] = batch.customer
    logged = n_conv + np.nonzero(rng.random(n_non) < 0.35)[0]
    k_day = max(1, int(np.searchsorted(c.signup_us, day_start, side="right")))
    cust[logged] = sample_prefix(rng, c.cumw, np.full(len(logged), k_day))
    has_cust = cust >= 0
    country = np.where(
        has_cust, c.country[np.maximum(cust, 0)], weighted_choice(rng, [x.weight for x in ref.COUNTRIES], S)
    ).astype(np.int64)

    L = np.empty(S, dtype=np.int64)
    L[:n_conv] = 4 + rng.geometric(0.22, n_conv)
    L[n_conv:] = np.minimum(rng.geometric(0.27, n_non), 40)

    source = weighted_choice(rng, [s[3] for s in ref.TRAFFIC_SOURCES], S)
    paid_source = np.array([s[1] in ("cpc", "paid_social", "display", "email") for s in ref.TRAFFIC_SOURCES])[
        source
    ]
    campaign = np.where(paid_source, rng.integers(0, len(ref.CAMPAIGNS), S), -1)

    session_id = uuid4_strings(rng, S)
    anonymous_id = pc.if_else(
        pa.array(has_cust),
        hashed_uuid_strings(np.maximum(cust, 0) * 3 + platform, salt=cfg.seed),
        uuid4_strings(rng, S),
    )
    ip = join(
        take_strings([str(o) for o in ref.IP_FIRST_OCTETS], rng.integers(0, len(ref.IP_FIRST_OCTETS), S)),
        ".",
        int_to_str(rng.integers(0, 256, S)),
        ".",
        int_to_str(rng.integers(0, 256, S)),
        ".",
        int_to_str(rng.integers(1, 255, S)),
        sep="",
    )
    is_mobile = platform > 0
    minor = (world.dates[day] - APP_VERSION_EPOCH).days // 28
    app_minor = np.maximum(0, minor - np.minimum(rng.geometric(0.55, S) - 1, 6))
    app_version = join("5.", int_to_str(app_minor), ".", int_to_str(rng.integers(0, 3, S)))
    app_version = pc.if_else(pa.array(is_mobile), app_version, pa.scalar(None, pa.string()))
    ua_start = np.array([s for s, _ in UA_RANGES])[platform]
    ua_len = np.array([n for _, n in UA_RANGES])[platform]
    ua_idx = ua_start + rng.integers(0, ua_len)
    user_agent = join(
        take_strings([b for b, _ in UA_POOL], ua_idx),
        pc.fill_null(app_version, ""),
        take_strings([a for _, a in UA_POOL], ua_idx),
    )

    # -- zdarzenia w sesjach --------------------------------------------------------------------
    seg, pos = segment_positions(L)
    N = len(seg)
    gaps = rng.exponential(25 * US_PER_SECOND, N).astype(np.int64)
    gaps[pos == 0] = 0
    cs = np.cumsum(gaps)
    starts = np.cumsum(L) - L
    offset = cs - np.repeat(cs[starts], L)
    duration = offset[starts + L - 1]
    sess_start = np.empty(S, dtype=np.int64)
    sess_start[:n_conv] = batch.created - duration[:n_conv]
    sess_start[n_conv:] = day_start + world.intraday_us(rng, n_non)
    true_ts = sess_start[seg] + offset

    etype = weighted_choice(rng, BROWSE_WEIGHTS, N).astype(np.int8)
    etype[pos == 0] = E["page_view"]
    conv_ev = is_conv[seg]
    from_end = L[seg] - 1 - pos
    tail = (E["purchase"], E["begin_checkout"], E["view_cart"], E["add_to_cart"], E["product_view"])
    for k, t in enumerate(tail):
        etype[conv_ev & (from_end == k)] = t

    k_prod = max(1, int(np.searchsorted(p.created_us, day_start, side="right")))
    product = sample_prefix(rng, p.cumw, np.full(N, k_prod))
    first_item = np.searchsorted(batch.item_row, np.arange(batch.n))
    order_first_product = batch.item_product[first_item]
    conv_tail = conv_ev & ((from_end == 3) | (from_end == 4))
    product[conv_tail] = order_first_product[seg[conv_tail]]
    has_product = np.isin(etype, PRODUCT_EVENTS)
    is_page = etype == E["page_view"]
    category_page = is_page & (rng.random(N) < 0.45)
    leaf_for_page = rng.integers(0, len(ref.LEAVES), N)
    category_id = np.where(has_product, LEAF_CATEGORY_ID[p.leaf[product]], LEAF_CATEGORY_ID[leaf_for_page])

    search_idx = rng.integers(0, len(_TERMS), N) + np.where(rng.random(N) < 0.05, len(_TERMS), 0)
    is_search = etype == E["search"]
    is_purchase = etype == E["purchase"]
    is_cart = (etype == E["add_to_cart"]) | (etype == E["remove_from_cart"])

    page_path = pc.choose(
        pa.array(etype),
        pc.if_else(pa.array(category_page), take_strings(LEAF_PATHS, leaf_for_page), pa.scalar("/")),
        join("/p/", int_to_str(product + 1)),
        take_strings(SEARCH_PATH_POOL, search_idx),
        join("/p/", int_to_str(product + 1)),
        join("/p/", int_to_str(product + 1)),
        join("/p/", int_to_str(product + 1)),
        pa.array(np.full(N, "/koszyk")),
        pa.array(np.full(N, "/zamowienie")),
        pa.array(np.full(N, "/zamowienie/potwierdzenie")),
    )

    quantity = np.where(is_cart, 1 + (rng.random(N) < 0.12) * rng.integers(1, 3, N), 0)
    price_local = local_price_cents(p.price_eur_cents_at(product, true_ts), country[seg])
    order_row = np.where(is_purchase, seg, 0)
    price = np.where(is_purchase, batch.total[np.minimum(order_row, max(batch.n - 1, 0))], price_local)
    has_price = has_product | is_purchase
    order_id = np.where(is_purchase, batch.order_id[np.minimum(order_row, max(batch.n - 1, 0))], 0)

    results = np.where(rng.random(N) < 0.03, 0, rng.integers(1, 480, N))
    list_name = take_strings(PRODUCT_LISTS, rng.integers(0, len(PRODUCT_LISTS), N))
    position = rng.integers(1, 48, N)
    safe_row = np.minimum(order_row, max(batch.n - 1, 0))
    properties = pc.if_else(
        pa.array(is_search),
        _json_obj(("results_count", int_to_str(results), False)),
        pc.if_else(
            pa.array(etype == E["product_view"]),
            _json_obj(("list", list_name, True), ("position", int_to_str(position), False)),
            pc.if_else(
                pa.array(is_purchase),
                _json_obj(
                    ("items_count", int_to_str(batch.items_count[safe_row]), False),
                    ("payment_method", take_strings(ref.PAYMENT_METHODS, batch.method[safe_row]), True),
                ),
                pa.scalar(None, pa.string()),
            ),
        ),
    )

    # -- czas dostarczenia: opóźnienia, tryb offline, rozjechane zegary ---------------------------
    mobile_ev = is_mobile[seg]
    delay = rng.lognormal(np.log(0.4 * US_PER_SECOND), 0.8, N).astype(np.int64)
    delay += np.where(mobile_ev, rng.integers(0, 20 * US_PER_SECOND, N), 0)
    late_session = is_mobile & (rng.random(S) < cfg.late_rate)
    late_delay = np.clip(
        rng.lognormal(np.log(45 * US_PER_MINUTE), 1.3, S),
        2 * US_PER_MINUTE,
        cfg.max_lateness_hours * US_PER_HOUR,
    ).astype(np.int64)
    received = true_ts + delay + np.where(late_session, late_delay, 0)[seg]
    skewed = rng.random(S) < cfg.clock_skew_rate
    skew = np.where(skewed, rng.choice(np.array([-1, 1]), S) * rng.integers(1, 49, S) * US_PER_HOUR, 0)
    event_ts = (true_ts + skew[seg]) // 1000 * 1000  # urządzenia wysyłają milisekundy

    # -- składanie tabeli ---------------------------------------------------------------------------
    sess_idx = pa.array(seg)
    first_ev = pos == 0
    src_idx = np.where(first_ev, source[seg], 0)
    table = pa.table(
        {
            "event_id": uuid4_strings(rng, N),
            "event_type": take_strings(EVENT_TYPES, etype),
            "event_ts": ts(event_ts),
            "received_at": ts(received),
            "session_id": session_id.take(sess_idx),
            "anonymous_id": anonymous_id.take(sess_idx),
            "customer_id": nullable(cust[seg] + 1, ~has_cust[seg], pa.int64()),
            "platform": take_strings(ref.PLATFORMS, platform[seg]),
            "app_version": app_version.take(sess_idx),
            "user_agent": user_agent.take(sess_idx),
            "ip_address": ip.take(sess_idx),
            "country": take_strings(ref.COUNTRY_CODES, country[seg]),
            "page_path": page_path,
            "referrer": take_strings(
                [s[2] for s in ref.TRAFFIC_SOURCES] + [None],
                np.where(first_ev, src_idx, len(ref.TRAFFIC_SOURCES)),
            ),
            "utm_source": take_strings(
                [s[0] for s in ref.TRAFFIC_SOURCES] + [None],
                np.where(first_ev, src_idx, len(ref.TRAFFIC_SOURCES)),
            ),
            "utm_medium": take_strings(
                [s[1] for s in ref.TRAFFIC_SOURCES] + [None],
                np.where(first_ev, src_idx, len(ref.TRAFFIC_SOURCES)),
            ),
            "utm_campaign": take_strings(
                [*ref.CAMPAIGNS, None],
                np.where(first_ev & (campaign[seg] >= 0), campaign[seg], len(ref.CAMPAIGNS)),
            ),
            "product_id": nullable(product + 1, ~has_product, pa.int64()),
            "category_id": nullable(category_id, ~(has_product | category_page), pa.int32()),
            "search_query": pc.if_else(
                pa.array(is_search), take_strings(SEARCH_POOL, search_idx), pa.scalar(None, pa.string())
            ),
            "quantity": nullable(quantity, ~is_cart, pa.int32()),
            "price": money(price, ~has_price),
            "currency": pc.if_else(
                pa.array(has_price),
                take_strings(COUNTRY_CURRENCY, country[seg]),
                pa.scalar(None, pa.string()),
            ),
            "order_id": nullable(order_id, ~is_purchase, pa.int64()),
            "properties": properties,
        }
    )

    # -- anomalia: utrata zdarzeń z Androida -----------------------------------------------------------
    keep = np.ones(N, dtype=bool)
    drop = world.anomaly("clickstream_android_drop")
    if drop is not None and drop.day_index == day:
        keep &= ~((platform[seg] == 1) & (rng.random(N) < drop.details["drop_ratio"]))

    # -- uszkodzone rekordy -------------------------------------------------------------------------------
    invalid = rng.random(N) < cfg.invalid_rate
    kind = rng.integers(0, 4, N)
    table = _corrupt(table, invalid, kind, rng)

    # -- duplikaty (ponowne wysłanie) -----------------------------------------------------------------------
    dup_p = np.full(N, cfg.duplicate_rate)
    storm = world.anomaly("clickstream_retry_storm")
    if storm is not None and storm.day_index == day:
        hour = (received - day_start) // US_PER_HOUR
        in_storm = (hour >= storm.details["start_hour_utc"]) & (
            hour < storm.details["start_hour_utc"] + storm.details["duration_hours"]
        )
        dup_p = np.where(in_storm, np.minimum(1.0, dup_p * storm.details["duplicate_multiplier"]), dup_p)
    dup = keep & (rng.random(N) < dup_p)
    retry_delay = np.where(
        rng.random(N) < 0.9,
        rng.exponential(5 * US_PER_SECOND, N),
        rng.uniform(US_PER_HOUR, 6 * US_PER_HOUR, N),
    ).astype(np.int64)
    base_idx = np.nonzero(keep)[0]
    dup_idx = np.nonzero(dup)[0]
    final_idx = np.concatenate([base_idx, dup_idx])
    final_received = np.concatenate([received[base_idx], received[dup_idx] + retry_delay[dup_idx]])
    order = np.argsort(final_received, kind="stable")
    table = table.take(pa.array(final_idx[order]))
    col = table.schema.get_field_index("received_at")
    return table.set_column(col, "received_at", ts(final_received[order]))


def _corrupt(table: pa.Table, invalid: np.ndarray, kind: np.ndarray, rng: np.random.Generator) -> pa.Table:
    if not invalid.any():
        return table

    def replace(name: str, mask: np.ndarray, value: pa.Array | pa.Scalar) -> None:
        nonlocal table
        if not mask.any():
            return
        i = table.schema.get_field_index(name)
        table = table.set_column(i, name, pc.if_else(pa.array(mask), value, table.column(name)))

    n = table.num_rows
    replace(
        "event_type",
        invalid & (kind == 0),
        take_strings(INVALID_EVENT_TYPES, rng.integers(0, len(INVALID_EVENT_TYPES), n)),
    )
    replace("session_id", invalid & (kind == 1), pa.scalar(None, pa.string()))
    has_price = table.column("price").is_valid().to_numpy(zero_copy_only=False)
    replace("price", invalid & (kind == 2) & has_price, pc.negate(table.column("price")))
    replace("customer_id", invalid & (kind == 3), pa.scalar(0, pa.int64()))
    return table
