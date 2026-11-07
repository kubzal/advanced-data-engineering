"""Zamówienia, pozycje zamówień i płatności — wraz z pełnym cyklem życia zamówienia.

Cykl życia: created → paid → shipped → delivered → (returned), albo → cancelled.
Płatność za pobraniem (cod): created → shipped → delivered (= paid).

``OrdersBatch`` przechowuje *pełny* cykl życia (także zdarzenia po końcu okresu). Tabele
„migawkowe” obcinają go do stanu na koniec okresu, a CDC i pliki przewoźników korzystają
z tych samych tablic. Dzięki temu wszystkie źródła są ze sobą spójne.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from . import reference as ref
from .arrays import (
    NULL_TS,
    US_PER_DAY,
    US_PER_HOUR,
    US_PER_MINUTE,
    US_PER_SECOND,
    Stream,
    base36_strings,
    clip_after,
    digits_strings,
    join,
    money,
    nullable,
    per_row_choice,
    random_hex_strings,
    rng_for,
    sample_prefix,
    segment_positions,
    take_strings,
    ts,
    weighted_choice,
)
from .world import COUNTRY_CURRENCY, LEAF_BULK, LEAF_CATEGORY_ID, LEAF_RETURN_RATE, local_price_cents

if TYPE_CHECKING:
    from .world import World

STATUSES = ("created", "paid", "shipped", "delivered", "returned", "cancelled")
LIFECYCLE = ("created", "paid", "shipped", "delivered", "returned", "cancelled")

_METHOD = {m: i for i, m in enumerate(ref.PAYMENT_METHODS)}
_PAYMENT_MIX = np.array([ref.PAYMENT_MIX[c] for c in ref.COUNTRY_CODES])
_CARRIER_MIX = np.array([ref.CARRIER_MIX[c] for c in ref.COUNTRY_CODES])
_SUCCESS = np.array([ref.PAYMENT_SUCCESS[m] for m in ref.PAYMENT_METHODS])
# próg darmowej dostawy i opłata za dostawę w walucie lokalnej (w groszach/centach)
_FREE_SHIPPING = {"PLN": 39_900, "EUR": 9_900, "CZK": 249_900}
_SHIPPING_FEE = {"PLN": 1_499, "EUR": 499, "CZK": 12_900}


@dataclass
class OrdersBatch:
    day: int
    order_id: np.ndarray
    customer: np.ndarray  # indeks klienta (customer_id = indeks + 1)
    country: np.ndarray
    platform: np.ndarray
    method: np.ndarray
    promo: np.ndarray  # -1 = brak kodu
    carrier: np.ndarray
    shipment_id: pa.Array
    failed_delivery: np.ndarray
    # pełny cykl życia (NULL_TS = nigdy)
    created: np.ndarray
    paid: np.ndarray
    shipped: np.ndarray
    delivered: np.ndarray
    returned: np.ndarray
    cancelled: np.ndarray
    # kwoty w walucie lokalnej (grosze/centy)
    subtotal: np.ndarray
    discount: np.ndarray
    shipping: np.ndarray
    total: np.ndarray
    items_count: np.ndarray
    # pozycje
    item_row: np.ndarray
    item_line: np.ndarray
    item_product: np.ndarray
    item_seller: np.ndarray
    item_qty: np.ndarray
    item_unit: np.ndarray
    item_discount: np.ndarray
    item_amount: np.ndarray
    # płatności
    pay_row: np.ndarray
    pay_type: np.ndarray  # 0 = charge, 1 = refund
    pay_ok: np.ndarray
    pay_failure: np.ndarray  # -1 = brak
    pay_ts: np.ndarray
    pay_id: pa.Array
    pay_card_brand: np.ndarray  # -1 = nie karta
    pay_last4: np.ndarray

    @property
    def n(self) -> int:
        return len(self.order_id)

    def lifecycle(self) -> np.ndarray:
        """Macierz (n, 6) znaczników czasu w kolejności ``LIFECYCLE``."""
        return np.stack(
            [self.created, self.paid, self.shipped, self.delivered, self.returned, self.cancelled], axis=1
        )


def status_codes_at(batch: OrdersBatch, rows: np.ndarray, t_us: np.ndarray | int) -> np.ndarray:
    """Status zamówień ``rows`` w chwili ``t_us`` (indeks w ``STATUSES``)."""
    t = np.broadcast_to(np.asarray(t_us, dtype=np.int64), np.shape(rows))
    s = np.zeros(len(rows), dtype=np.int8)
    for code, col in (
        (1, batch.paid),
        (2, batch.shipped),
        (3, batch.delivered),
        (4, batch.returned),
        (5, batch.cancelled),
    ):
        v = col[rows]
        s[(v != NULL_TS) & (v <= t)] = code
    return s


def generate_orders(world: World, day: int) -> OrdersBatch:
    cfg = world.cfg
    rng = rng_for(cfg.seed, Stream.ORDERS, day)
    n = int(world.day_orders[day])
    day_start = world.day_start_us(day)
    created = np.sort(day_start + world.intraday_us(rng, n))
    order_id = (world.order_id_offsets[day] + np.arange(1, n + 1)).astype(np.int64)

    # -- klient: musi być zarejestrowany i nie może mieć usuniętych danych -----------------
    c = world.customers
    k = np.searchsorted(c.signup_us, created, side="right")
    cust = sample_prefix(rng, c.cumw, k)
    for _ in range(10):
        bad = (c.erased_us[cust] != NULL_TS) & (c.erased_us[cust] <= created)
        if not bad.any():
            break
        cust[bad] = sample_prefix(rng, c.cumw, k[bad])
    bad = (c.erased_us[cust] != NULL_TS) & (c.erased_us[cust] <= created)
    cust[bad] = 0
    country = c.country[cust].astype(np.int64)

    platform = weighted_choice(rng, [0.55, 0.25, 0.20], n).astype(np.int8)
    method = per_row_choice(rng, _PAYMENT_MIX, country).astype(np.int8)

    # -- pozycje zamówienia ---------------------------------------------------------------
    n_items = np.minimum(rng.geometric(0.55, n), 8)
    row, line = segment_positions(n_items)
    m = len(row)
    p = world.products
    kp = np.searchsorted(p.created_us, created[row], side="right")
    prod = sample_prefix(rng, p.cumw, kp)
    bulk = LEAF_BULK[p.leaf[prod]]
    qty = 1 + np.where(rng.random(m) < np.where(bulk, 0.45, 0.10), rng.integers(1, 4, m), 0)
    unit = local_price_cents(p.price_eur_cents_at(prod, created[row]), country[row])
    gross = unit * qty
    promo_boost = (
        2.5
        if world.dates[day].month in (11, 12) and world.day_orders[day] > np.median(world.day_orders) * 1.5
        else 1.0
    )
    discounted = rng.random(m) < 0.08 * promo_boost
    pct = rng.choice(np.array([5, 10, 15, 20, 30]), m)
    item_discount = np.where(discounted, (gross * pct) // 100, 0).astype(np.int64)
    item_amount = gross - item_discount

    subtotal = np.bincount(row, weights=gross, minlength=n).astype(np.int64)
    discount = np.bincount(row, weights=item_discount, minlength=n).astype(np.int64)
    promo = np.where(discount > 0, rng.integers(0, len(ref.PROMO_CODES), n), -1).astype(np.int16)
    currency = np.array(COUNTRY_CURRENCY)[country]
    free_from = np.array([_FREE_SHIPPING[x] for x in currency])
    fee = np.array([_SHIPPING_FEE[x] for x in currency])
    net = subtotal - discount
    shipping = np.where(net >= free_from, 0, fee).astype(np.int64)
    total = net + shipping

    first_item = np.searchsorted(row, np.arange(n))
    first_product = prod[first_item]
    seller_idx = p.seller[prod]
    first_seller = seller_idx[first_item]

    # -- płatność ---------------------------------------------------------------------------
    is_cod = method == _METHOD["cod"]
    is_bank = method == _METHOD["bank_transfer"]
    ok1 = (rng.random(n) < _SUCCESS[method]) | is_cod
    retried = ~ok1 & (rng.random(n) < 0.75)
    ok2 = retried & (rng.random(n) < 0.8)
    fast_delay = rng.integers(5 * US_PER_SECOND, 3 * US_PER_MINUTE, n)
    bank_delay = rng.integers(2 * US_PER_HOUR, 30 * US_PER_HOUR, n)
    attempt1 = created + np.where(is_bank, bank_delay, fast_delay)
    attempt2 = attempt1 + rng.integers(US_PER_MINUTE, 15 * US_PER_MINUTE, n)
    paid = np.where(ok1, attempt1, np.where(ok2, attempt2, NULL_TS))
    paid[is_cod] = NULL_TS
    unpaid = ~is_cod & ~ok1 & ~ok2

    # -- anulowanie, wysyłka, dostawa, zwrot --------------------------------------------------
    ready = np.where(is_cod, created, paid)
    handling_h = world.sellers.handling_hours[first_seller] * rng.lognormal(0, 0.4, n)
    handling = (np.clip(handling_h, 2, 120) * US_PER_HOUR).astype(np.int64)
    cancelled = np.where(unpaid, created + np.where(is_bank, 72 * US_PER_HOUR, US_PER_HOUR), NULL_TS)
    cust_cancel = ~unpaid & (rng.random(n) < 0.025)
    cancel_at = ready + (rng.random(n) * handling * 0.6).astype(np.int64) + 5 * US_PER_MINUTE
    cancelled = np.where(cust_cancel, cancel_at, cancelled)

    shipped = np.where(cancelled == NULL_TS, ready + handling, NULL_TS)
    seller_country = world.sellers.country[first_seller]
    domestic = seller_country == country
    transit_days = np.clip(rng.lognormal(np.log(np.where(domestic, 1.3, 3.2)), 0.35), 0.4, 12)
    delivered = np.where(shipped != NULL_TS, shipped + (transit_days * US_PER_DAY).astype(np.int64), NULL_TS)
    failed_delivery = (delivered != NULL_TS) & (rng.random(n) < 0.02)
    delivered = np.where(failed_delivery, delivered + US_PER_DAY, delivered)
    paid = np.where(is_cod & (delivered != NULL_TS), delivered, paid)

    return_rate = LEAF_RETURN_RATE[p.leaf[first_product]]
    will_return = (delivered != NULL_TS) & (rng.random(n) < return_rate)
    returned = np.where(will_return, delivered + rng.integers(2 * US_PER_DAY, 14 * US_PER_DAY, n), NULL_TS)

    carrier = per_row_choice(rng, _CARRIER_MIX, country).astype(np.int8)
    shipment_id = pc.choose(
        pa.array(carrier),
        join("SP", digits_strings(rng.integers(0, 10**10, n), 10), "PL"),
        digits_strings(rng.integers(10**13, 10**14, n), 14),
        join("QS", base36_strings(rng.integers(0, 36**10, n, dtype=np.int64), 10)),
    )

    # -- rekordy płatności ------------------------------------------------------------------------
    pay_parts: list[tuple[np.ndarray, int, np.ndarray, np.ndarray]] = []  # (wiersze, typ, ok, ts)
    non_cod = np.nonzero(~is_cod)[0]
    pay_parts.append((non_cod, 0, ok1[non_cod], attempt1[non_cod]))
    r2 = np.nonzero(retried)[0]
    pay_parts.append((r2, 0, ok2[r2], attempt2[r2]))
    cod_paid = np.nonzero(is_cod & (delivered != NULL_TS))[0]
    pay_parts.append((cod_paid, 0, np.ones(len(cod_paid), bool), delivered[cod_paid]))
    refund_cancel = np.nonzero(cust_cancel & (paid != NULL_TS) & ~is_cod)[0]
    pay_parts.append(
        (
            refund_cancel,
            1,
            np.ones(len(refund_cancel), bool),
            cancelled[refund_cancel] + rng.integers(US_PER_HOUR, 3 * US_PER_DAY, len(refund_cancel)),
        )
    )
    refund_return = np.nonzero(will_return)[0]
    pay_parts.append(
        (
            refund_return,
            1,
            np.ones(len(refund_return), bool),
            returned[refund_return] + rng.integers(US_PER_DAY, 5 * US_PER_DAY, len(refund_return)),
        )
    )
    pay_row = np.concatenate([x[0] for x in pay_parts]).astype(np.int64)
    pay_type = np.concatenate([np.full(len(x[0]), x[1], np.int8) for x in pay_parts])
    pay_ok = np.concatenate([x[2] for x in pay_parts]).astype(bool)
    pay_ts = np.concatenate([x[3] for x in pay_parts]).astype(np.int64)
    order = np.argsort(pay_ts, kind="stable")
    pay_row, pay_type, pay_ok, pay_ts = pay_row[order], pay_type[order], pay_ok[order], pay_ts[order]
    np_ = len(pay_row)
    is_card = method[pay_row] == _METHOD["card"]
    card_brand = np.where(is_card, weighted_choice(rng, [w for _, w in ref.CARD_BRANDS], np_), -1).astype(
        np.int8
    )
    pay_failure = np.where(pay_ok, -1, rng.integers(0, len(ref.FAILURE_CODES), np_)).astype(np.int8)

    return OrdersBatch(
        day=day,
        order_id=order_id,
        customer=cust.astype(np.int64),
        country=country,
        platform=platform,
        method=method,
        promo=promo,
        carrier=carrier,
        shipment_id=shipment_id,
        failed_delivery=failed_delivery,
        created=created,
        paid=paid,
        shipped=shipped,
        delivered=delivered,
        returned=returned,
        cancelled=cancelled,
        subtotal=subtotal,
        discount=discount,
        shipping=shipping,
        total=total,
        items_count=n_items.astype(np.int32),
        item_row=row,
        item_line=(line + 1).astype(np.int32),
        item_product=prod.astype(np.int64),
        item_seller=seller_idx.astype(np.int64),
        item_qty=qty.astype(np.int32),
        item_unit=unit,
        item_discount=item_discount,
        item_amount=item_amount,
        pay_row=pay_row,
        pay_type=pay_type,
        pay_ok=pay_ok,
        pay_failure=pay_failure,
        pay_ts=pay_ts,
        pay_id=random_hex_strings(rng, np_, 24, prefix="pay_"),
        pay_card_brand=card_brand,
        pay_last4=rng.integers(0, 10_000, np_).astype(np.int16),
    )


# ---------------------------------------------------------------------------
# Tabele
# ---------------------------------------------------------------------------


def orders_columns(
    world: World, batch: OrdersBatch, rows: np.ndarray, as_of: np.ndarray | int
) -> dict[str, pa.Array]:
    """Kolumny tabeli ``orders`` dla wierszy ``rows`` w stanie na chwilę ``as_of``.

    Używane zarówno przez migawkę (as_of = koniec okresu), jak i przez CDC (as_of = moment zmiany).
    """
    rows = np.asarray(rows, dtype=np.int64)
    as_of_arr = np.broadcast_to(np.asarray(as_of, dtype=np.int64), rows.shape)

    def at(col: np.ndarray) -> np.ndarray:
        v = col[rows].copy()
        v[(v != NULL_TS) & (v > as_of_arr)] = NULL_TS
        return v

    created, paid, shipped = at(batch.created), at(batch.paid), at(batch.shipped)
    delivered, returned, cancelled = at(batch.delivered), at(batch.returned), at(batch.cancelled)
    updated = np.max(np.stack([created, paid, shipped, delivered, returned, cancelled]), axis=0)
    status = status_codes_at(batch, rows, as_of_arr)
    profile = world.customer_profile(batch.customer[rows], batch.created[rows])
    not_shipped = shipped == NULL_TS
    country = batch.country[rows]
    return {
        "order_id": pa.array(batch.order_id[rows]),
        "customer_id": pa.array(batch.customer[rows] + 1),
        "status": take_strings(STATUSES, status),
        "currency": take_strings(COUNTRY_CURRENCY, country),
        "platform": take_strings(ref.PLATFORMS, batch.platform[rows]),
        "payment_method": take_strings(ref.PAYMENT_METHODS, batch.method[rows]),
        "promo_code": take_strings(
            [*ref.PROMO_CODES, None], np.where(batch.promo[rows] < 0, len(ref.PROMO_CODES), batch.promo[rows])
        ),
        "items_count": pa.array(batch.items_count[rows], type=pa.int32()),
        "subtotal_amount": money(batch.subtotal[rows]),
        "discount_amount": money(batch.discount[rows]),
        "shipping_amount": money(batch.shipping[rows]),
        "total_amount": money(batch.total[rows]),
        "shipping_country": take_strings(ref.COUNTRY_CODES, country),
        "shipping_city": profile["city"],
        "shipping_postal_code": profile["postal_code"],
        "shipping_street": profile["street_address"],
        "carrier": pc.if_else(
            pa.array(not_shipped),
            pa.scalar(None, pa.string()),
            take_strings(ref.CARRIERS, batch.carrier[rows]),
        ),
        "shipment_id": pc.if_else(
            pa.array(not_shipped), pa.scalar(None, pa.string()), batch.shipment_id.take(rows)
        ),
        "created_at": ts(created),
        "paid_at": ts(paid),
        "shipped_at": ts(shipped),
        "delivered_at": ts(delivered),
        "cancelled_at": ts(cancelled),
        "returned_at": ts(returned),
        "updated_at": ts(updated),
    }


def orders_table(world: World, batch: OrdersBatch) -> pa.Table:
    rows = np.arange(batch.n)
    return pa.table(orders_columns(world, batch, rows, world.end_us))


def items_columns(world: World, batch: OrdersBatch, items: np.ndarray) -> dict[str, pa.Array]:
    items = np.asarray(items, dtype=np.int64)
    unit = batch.item_unit[items].copy()
    amount = batch.item_amount[items].copy()
    anomaly = world.anomaly("order_items_price_in_minor_units")
    if anomaly is not None and anomaly.day_index == batch.day:
        bug = batch.item_seller[items] + 1 == anomaly.details["seller_id"]
        unit[bug] *= 100
        amount[bug] *= 100
    p = world.products
    prod = batch.item_product[items]
    return {
        "order_id": pa.array(batch.order_id[batch.item_row[items]]),
        "line_number": pa.array(batch.item_line[items], type=pa.int32()),
        "product_id": pa.array(prod + 1),
        "seller_id": pa.array(batch.item_seller[items] + 1),
        "category_id": pa.array(LEAF_CATEGORY_ID[p.leaf[prod]], type=pa.int32()),
        "quantity": pa.array(batch.item_qty[items], type=pa.int32()),
        "unit_price": money(unit),
        "discount_amount": money(batch.item_discount[items]),
        "line_amount": money(amount),
        "currency": take_strings(COUNTRY_CURRENCY, batch.country[batch.item_row[items]]),
    }


def items_table(world: World, batch: OrdersBatch) -> pa.Table:
    return pa.table(items_columns(world, batch, np.arange(len(batch.item_row))))


def payments_table(world: World, batch: OrdersBatch) -> pa.Table:
    """Płatności widoczne do końca okresu (rekordy z przyszłości są pomijane)."""
    keep = np.nonzero(batch.pay_ts <= world.end_us)[0]
    rows = batch.pay_row[keep]
    brand = batch.pay_card_brand[keep]
    is_card = brand >= 0
    failure = batch.pay_failure[keep]
    profile = world.customer_profile(batch.customer[rows], batch.pay_ts[keep])
    return pa.table(
        {
            "payment_id": batch.pay_id.take(keep),
            "order_id": pa.array(batch.order_id[rows]),
            "customer_id": pa.array(batch.customer[rows] + 1),
            "type": take_strings(("charge", "refund"), batch.pay_type[keep]),
            "status": take_strings(("failed", "succeeded"), batch.pay_ok[keep].astype(np.int8)),
            "failure_code": take_strings(
                [*ref.FAILURE_CODES, None], np.where(failure < 0, len(ref.FAILURE_CODES), failure)
            ),
            "method": take_strings(ref.PAYMENT_METHODS, batch.method[rows]),
            "card_brand": take_strings(
                [b for b, _ in ref.CARD_BRANDS] + [None], np.where(is_card, brand, len(ref.CARD_BRANDS))
            ),
            "card_last4": pc.if_else(
                pa.array(is_card), digits_strings(batch.pay_last4[keep], 4), pa.scalar(None, pa.string())
            ),
            "amount": money(batch.total[rows]),
            "currency": take_strings(COUNTRY_CURRENCY, batch.country[rows]),
            "payer_email": profile["email"],
            "created_at": ts(batch.pay_ts[keep]),
        }
    )


__all__ = [
    "LIFECYCLE",
    "STATUSES",
    "OrdersBatch",
    "generate_orders",
    "items_columns",
    "items_table",
    "orders_columns",
    "orders_table",
    "payments_table",
    "status_codes_at",
    "clip_after",
    "nullable",
]
