"""„Świat” NovaCart: kalendarz, encje (klienci, sprzedawcy, produkty) i plan anomalii.

World jest w pełni deterministyczny i budowany wyłącznie z ``Config``. Każdy proces roboczy
odtwarza go samodzielnie, zamiast dostawać go przez pickle. Przechowujemy tylko tablice
liczbowe; napisy (imiona, adresy, e-maile) budujemy na żądanie dla wybranych wierszy.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from . import reference as ref
from .arrays import (
    NULL_TS,
    US_PER_DAY,
    US_PER_HOUR,
    Stream,
    digits_strings,
    int_to_str,
    join,
    rng_for,
    sample_prefix,
    take_strings,
    weighted_choice,
)
from .config import Config

if TYPE_CHECKING:
    from .orders import OrdersBatch

EPOCH = date(1970, 1, 1)


def date_to_us(d: date) -> int:
    return (d - EPOCH).days * US_PER_DAY


def us_to_datetime(us: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=int(us))


# ---------------------------------------------------------------------------
# Kalendarz i sezonowość
# ---------------------------------------------------------------------------

WEEKDAY_FACTOR = np.array([0.97, 0.98, 1.00, 1.01, 1.03, 0.88, 1.13])  # pon..niedz
MONTH_FACTOR = np.array([0.82, 0.84, 0.95, 0.96, 1.00, 0.94, 0.90, 0.92, 1.00, 1.06, 1.22, 1.30])
# Rozkład godzinowy zamówień i sesji w czasie lokalnym (CET); szczyt wieczorem
HOUR_WEIGHTS_LOCAL = np.array(
    [
        0.8,
        0.5,
        0.3,
        0.2,
        0.2,
        0.3,
        0.7,
        1.4,
        2.4,
        3.3,
        3.9,
        4.2,
        4.4,
        4.5,
        4.4,
        4.4,
        4.6,
        5.0,
        5.6,
        6.3,
        6.9,
        7.0,
        5.6,
        3.0,
    ]
)
HOUR_WEIGHTS_UTC = np.roll(HOUR_WEIGHTS_LOCAL, -1)  # CET = UTC+1 (pomijamy czas letni)


def black_friday(year: int) -> date:
    nov30 = date(year, 11, 30)
    return nov30 - timedelta(days=(nov30.weekday() - 4) % 7)


def special_day_factor(d: date) -> float:
    bf = black_friday(d.year)
    if d == bf:
        return 2.8
    if d == bf + timedelta(days=1):
        return 1.7
    if d == bf + timedelta(days=3):  # Cyber Monday
        return 2.0
    if bf - timedelta(days=5) <= d < bf:  # tydzień przed BF: klienci czekają
        return 0.9
    if d.month == 12 and d.day in (24, 25, 26):
        return 0.45
    if d.month == 12 and 1 <= d.day <= 20:
        return 1.12
    if d.month == 12 and d.day == 31:
        return 0.6
    if d.month == 1 and d.day == 1:
        return 0.5
    return 1.0


# ---------------------------------------------------------------------------
# Encje
# ---------------------------------------------------------------------------


@dataclass
class Customers:
    n: int
    signup_us: np.ndarray  # posortowane rosnąco: customer_id = indeks + 1
    country: np.ndarray
    gender: np.ndarray
    first_idx: np.ndarray  # indeks w FIRST_POOL
    last_idx: np.ndarray  # indeks w LAST_POOL_M / LAST_POOL_F
    birth_day: np.ndarray  # dni od epoki
    email_pattern: np.ndarray
    email_num: np.ndarray  # -1 = brak liczby
    email_domain: np.ndarray  # indeks w DOMAIN_POOL
    email2_num: np.ndarray
    email2_domain: np.ndarray
    email_change_us: np.ndarray
    phone_prefix: np.ndarray  # indeks w PHONE_PREFIX_POOL
    phone_number: np.ndarray
    phone_spaced: np.ndarray  # część numerów zapisana ze spacjami (bałagan w danych wejściowych)
    city: np.ndarray  # indeks w CITY_POOL (adres 1)
    street: np.ndarray
    house: np.ndarray
    apt: np.ndarray
    postal: np.ndarray
    move_us: np.ndarray  # przeprowadzka → adres 2
    city2: np.ndarray
    street2: np.ndarray
    house2: np.ndarray
    apt2: np.ndarray
    postal2: np.ndarray
    consent: np.ndarray
    consent_change_us: np.ndarray
    erased_us: np.ndarray  # żądanie usunięcia danych (RODO)
    cumw: np.ndarray  # skumulowane wagi aktywności zakupowej

    @property
    def ids(self) -> np.ndarray:
        return np.arange(1, self.n + 1, dtype=np.int64)


@dataclass
class Sellers:
    n: int
    joined_us: np.ndarray  # posortowane rosnąco
    country: np.ndarray
    word: np.ndarray
    suffix: np.ndarray
    city: np.ndarray
    rating: np.ndarray
    tier: np.ndarray
    commission_bp: np.ndarray  # prowizja w punktach bazowych
    handling_hours: np.ndarray  # mediana czasu przygotowania wysyłki
    cumw: np.ndarray


@dataclass
class Products:
    n: int
    created_us: np.ndarray  # posortowane rosnąco
    leaf: np.ndarray  # indeks w ref.LEAVES
    seller: np.ndarray  # indeks sprzedawcy (seller_id = indeks + 1)
    brand: np.ndarray  # indeks w BRAND_POOL
    noun: np.ndarray  # indeks w NOUN_POOL
    model: np.ndarray
    color: np.ndarray
    base_cents_eur: np.ndarray
    weight_g: np.ndarray
    change_us: np.ndarray  # (n, 3) momenty zmian ceny
    change_factor: np.ndarray  # (n, 3) mnożniki ceny
    cumw: np.ndarray

    def price_eur_cents_at(self, idx: np.ndarray, t_us: np.ndarray) -> np.ndarray:
        cu = self.change_us[idx]
        cf = self.change_factor[idx]
        t = np.asarray(t_us)[:, None]
        factor = np.where((cu != NULL_TS) & (cu <= t), cf, 1.0).prod(axis=1)
        return np.maximum(99, np.round(self.base_cents_eur[idx] * factor)).astype(np.int64)


# Słowniki spłaszczone do tablic (indeksy przechowujemy w encjach)
FIRST_POOL: list[str] = []
FIRST_RANGES: dict[tuple[int, int], tuple[int, int]] = {}  # (kraj, płeć) → (start, długość)
LAST_POOL_M: list[str] = []
LAST_POOL_F: list[str] = []
LAST_RANGES: dict[int, tuple[int, int]] = {}
CITY_POOL: list[str] = []
CITY_PREFIX: list[str] = []
CITY_COUNTRY: list[int] = []
CITY_RANGES: dict[int, tuple[int, int]] = {}
STREET_POOL: list[str] = []
STREET_RANGES: dict[int, tuple[int, int]] = {}
DOMAIN_POOL: list[str] = []
PHONE_PREFIX_POOL: list[str] = []


def _build_pools() -> None:
    for ci, c in enumerate(ref.COUNTRIES):
        for g, names in ((0, c.first_m), (1, c.first_f)):
            FIRST_RANGES[(ci, g)] = (len(FIRST_POOL), len(names))
            FIRST_POOL.extend(names)
        LAST_RANGES[ci] = (len(LAST_POOL_M), len(c.last))
        LAST_POOL_M.extend(m for m, _ in c.last)
        LAST_POOL_F.extend(f for _, f in c.last)
        CITY_RANGES[ci] = (len(CITY_POOL), len(c.cities))
        for city in c.cities:
            CITY_POOL.append(city.name)
            CITY_PREFIX.append(city.postal_prefix)
            CITY_COUNTRY.append(ci)
        STREET_RANGES[ci] = (len(STREET_POOL), len(c.streets))
        STREET_POOL.extend(c.streets)
        for d, _ in c.email_domains:
            if d not in DOMAIN_POOL:
                DOMAIN_POOL.append(d)
        for p in c.mobile_prefixes:
            PHONE_PREFIX_POOL.append(c.phone_prefix + p)


_build_pools()

BRAND_POOL: list[str] = [b for top in ref.CATEGORIES for b in top.brands]
BRAND_RANGES: list[tuple[int, int]] = []
_pos = 0
for _top in ref.CATEGORIES:
    BRAND_RANGES.append((_pos, len(_top.brands)))
    _pos += len(_top.brands)
NOUN_POOL: list[str] = [n for leaf in ref.LEAVES for n in leaf.leaf.nouns]  # type: ignore[union-attr]
NOUN_RANGES: list[tuple[int, int]] = []
_pos = 0
for _leaf in ref.LEAVES:
    NOUN_RANGES.append((_pos, len(_leaf.leaf.nouns)))  # type: ignore[union-attr]
    _pos += len(_leaf.leaf.nouns)  # type: ignore[union-attr]
LEAF_CATEGORY_ID = np.array([c.category_id for c in ref.LEAVES], dtype=np.int32)
LEAF_TOP = np.array([c.top_index for c in ref.LEAVES], dtype=np.int16)
LEAF_RETURN_RATE = np.array([c.leaf.return_rate for c in ref.LEAVES])  # type: ignore[union-attr]
LEAF_BULK = np.array([c.leaf.bulk for c in ref.LEAVES])  # type: ignore[union-attr]
COUNTRY_CURRENCY = [c.currency for c in ref.COUNTRIES]
COUNTRY_EUR_RATE = np.array([c.eur_rate for c in ref.COUNTRIES])


def _ranged_pick(rng: np.random.Generator, groups: np.ndarray, ranges: dict | list) -> np.ndarray:
    starts = np.array([ranges[g][0] for g in range(len(ranges))], dtype=np.int64)
    lens = np.array([ranges[g][1] for g in range(len(ranges))], dtype=np.int64)
    return starts[groups] + rng.integers(0, lens[groups])


def _pick_city(rng: np.random.Generator, country: np.ndarray) -> np.ndarray:
    out = np.empty(len(country), dtype=np.int32)
    for ci, c in enumerate(ref.COUNTRIES):
        mask = country == ci
        if mask.any():
            start, _ = CITY_RANGES[ci]
            out[mask] = start + weighted_choice(rng, [x.weight for x in c.cities], int(mask.sum()))
    return out


def _random_times(rng: np.random.Generator, start_us: int, end_us: int, n: int) -> np.ndarray:
    return rng.integers(start_us, max(start_us + 1, end_us), size=n, dtype=np.int64)


def _optional_times(rng: np.random.Generator, prob: float, after_us: np.ndarray, end_us: int) -> np.ndarray:
    """Z prawdopodobieństwem ``prob`` zdarzenie w losowym momencie między ``after_us`` a końcem okresu."""
    n = len(after_us)
    out = np.full(n, NULL_TS, dtype=np.int64)
    hit = (rng.random(n) < prob) & (after_us < end_us - US_PER_DAY)
    span = (end_us - after_us[hit]).astype(np.float64)
    out[hit] = after_us[hit] + (rng.random(hit.sum()) * span).astype(np.int64) + US_PER_HOUR
    return out


@dataclass(frozen=True)
class Anomaly:
    kind: str
    day_index: int
    date: str
    description: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "date": self.date, "description": self.description, **self.details}


class World:
    """Wszystkie dane referencyjne potrzebne do generowania zdarzeń dzień po dniu."""

    ORDERS_CACHE_SIZE = 64

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.start_us = date_to_us(cfg.start_date)
        self.end_us = date_to_us(cfg.end_date) + US_PER_DAY - 1  # koniec ostatniego dnia
        self.dates = [cfg.start_date + timedelta(days=i) for i in range(cfg.days)]
        self.day_orders = self._daily_order_counts()
        self.order_id_offsets = 1_000_000 + np.concatenate([[0], np.cumsum(self.day_orders)[:-1]])
        self.sellers = self._build_sellers()
        self.customers = self._build_customers()
        self.products = self._build_products()
        self.anomalies = self._plan_anomalies()
        self._orders_cache: OrderedDict[int, OrdersBatch] = OrderedDict()

    # -- kalendarz ---------------------------------------------------------

    def day_start_us(self, day: int) -> int:
        return self.start_us + day * US_PER_DAY

    def day_of(self, us: np.ndarray) -> np.ndarray:
        return (np.asarray(us) - self.start_us) // US_PER_DAY

    def _daily_order_counts(self) -> np.ndarray:
        cfg = self.cfg
        rng = rng_for(cfg.seed, Stream.CALENDAR)
        t = np.arange(cfg.days)
        growth = (1.0 + cfg.growth_per_year) ** (t / 365.0)
        season = np.array(
            [
                WEEKDAY_FACTOR[d.weekday()] * MONTH_FACTOR[d.month - 1] * special_day_factor(d)
                for d in self.dates
            ]
        )
        noise = rng.lognormal(0.0, 0.07, cfg.days)
        return np.maximum(1, np.round(cfg.orders_per_day * growth * season * noise)).astype(np.int64)

    def intraday_us(self, rng: np.random.Generator, n: int) -> np.ndarray:
        hours = weighted_choice(rng, HOUR_WEIGHTS_UTC, n)
        return hours * US_PER_HOUR + rng.integers(0, US_PER_HOUR, size=n)

    # -- encje ---------------------------------------------------------------

    def _build_sellers(self) -> Sellers:
        cfg = self.cfg
        rng = rng_for(cfg.seed, Stream.SELLERS)
        n = cfg.sellers
        pre = rng.random(n) < 0.8
        joined = np.where(
            pre,
            _random_times(rng, self.start_us - 3 * 365 * US_PER_DAY, self.start_us - US_PER_DAY, n),
            _random_times(rng, self.start_us, self.end_us - 7 * US_PER_DAY, n),
        )
        # najstarszy sprzedawca zawsze istnieje przed startem
        joined[np.argmin(joined)] = self.start_us - 3 * 365 * US_PER_DAY
        joined.sort()
        country = weighted_choice(rng, [c.seller_weight for c in ref.COUNTRIES], n).astype(np.int8)
        weights = rng.lognormal(0.0, 1.4, n)
        return Sellers(
            n=n,
            joined_us=joined,
            country=country,
            word=rng.integers(0, len(ref.SELLER_WORDS), n).astype(np.int16),
            suffix=rng.integers(0, 10, n).astype(np.int16),
            city=_pick_city(rng, country),
            rating=np.clip(rng.normal(4.55, 0.25, n), 2.5, 5.0).round(2),
            tier=weighted_choice(rng, [0.7, 0.22, 0.08], n).astype(np.int8),
            commission_bp=rng.choice(np.array([800, 1000, 1200, 1500]), n),
            handling_hours=np.clip(rng.lognormal(np.log(20), 0.5, n), 3, 96),
            cumw=np.cumsum(weights),
        )

    def _build_customers(self) -> Customers:
        cfg = self.cfg
        rng = rng_for(cfg.seed, Stream.CUSTOMERS)
        n = cfg.customers
        start, end = self.start_us, self.end_us
        pre = rng.random(n) < 0.6
        # klienci zarejestrowani przed startem (3 lata wstecz) i w trakcie okresu (rosnący napływ)
        in_period = start + (np.sqrt(rng.random(n)) * (end - start)).astype(np.int64)
        signup = np.where(
            pre, _random_times(rng, start - 3 * 365 * US_PER_DAY, start - US_PER_HOUR, n), in_period
        )
        signup[0] = start - 3 * 365 * US_PER_DAY
        signup.sort()

        country = weighted_choice(rng, [c.weight for c in ref.COUNTRIES], n).astype(np.int8)
        gender = (rng.random(n) < 0.52).astype(np.int8)  # 1 = kobieta
        first = np.empty(n, dtype=np.int32)
        for ci in range(len(ref.COUNTRIES)):
            for g in (0, 1):
                mask = (country == ci) & (gender == g)
                s, ln = FIRST_RANGES[(ci, g)]
                first[mask] = s + rng.integers(0, ln, mask.sum())
        last = _ranged_pick(rng, country, LAST_RANGES).astype(np.int32)

        age_years = np.clip(rng.normal(38, 12, n), 18, 85)
        birth_day = ((date_to_us(self.cfg.end_date) // US_PER_DAY) - age_years * 365.25).astype(np.int32)

        def domain_pick(r: np.random.Generator) -> np.ndarray:
            out = np.empty(n, dtype=np.int16)
            for ci, c in enumerate(ref.COUNTRIES):
                mask = country == ci
                names = [d for d, _ in c.email_domains]
                chosen = weighted_choice(r, [w for _, w in c.email_domains], int(mask.sum()))
                out[mask] = np.array([DOMAIN_POOL.index(d) for d in names])[chosen]
            return out

        email_num = np.where(rng.random(n) < 0.55, rng.integers(1, 100, n), -1).astype(np.int16)
        prefix_start = []
        offset = 0
        for c in ref.COUNTRIES:
            prefix_start.append((offset, len(c.mobile_prefixes)))
            offset += len(c.mobile_prefixes)
        phone_prefix = _ranged_pick(rng, country, prefix_start).astype(np.int16)
        digits = np.array([c.phone_digits for c in ref.COUNTRIES])[country]
        phone_number = (rng.random(n) * (10.0**digits)).astype(np.int64)

        signup_or_start = np.maximum(signup, start)
        weights = rng.lognormal(0.0, 1.0, n)
        move_us = _optional_times(rng, 0.08, signup_or_start, end)
        erased_us = _optional_times(rng, 0.004, signup_or_start, end)
        erased_us[0] = NULL_TS  # klient nr 1 nigdy nie jest usuwany (bezpieczny wybór awaryjny)
        return Customers(
            n=n,
            signup_us=signup,
            country=country,
            gender=gender,
            first_idx=first,
            last_idx=last,
            birth_day=birth_day,
            email_pattern=rng.integers(0, 4, n).astype(np.int8),
            email_num=email_num,
            email_domain=domain_pick(rng),
            email2_num=rng.integers(1, 1000, n).astype(np.int16),
            email2_domain=domain_pick(rng),
            email_change_us=_optional_times(rng, 0.03, signup_or_start, end),
            phone_prefix=phone_prefix,
            phone_number=phone_number,
            phone_spaced=rng.random(n) < 0.05,
            city=_pick_city(rng, country),
            street=_ranged_pick(rng, country, STREET_RANGES).astype(np.int16),
            house=rng.integers(1, 180, n).astype(np.int16),
            apt=np.where(rng.random(n) < 0.55, rng.integers(1, 120, n), 0).astype(np.int16),
            postal=rng.integers(0, 10_000, n).astype(np.int32),
            move_us=move_us,
            city2=_pick_city(rng, country),
            street2=_ranged_pick(rng, country, STREET_RANGES).astype(np.int16),
            house2=rng.integers(1, 180, n).astype(np.int16),
            apt2=np.where(rng.random(n) < 0.55, rng.integers(1, 120, n), 0).astype(np.int16),
            postal2=rng.integers(0, 10_000, n).astype(np.int32),
            consent=rng.random(n) < 0.42,
            consent_change_us=_optional_times(rng, 0.05, signup_or_start, end),
            erased_us=erased_us,
            cumw=np.cumsum(weights),
        )

    def _build_products(self) -> Products:
        cfg = self.cfg
        rng = rng_for(cfg.seed, Stream.PRODUCTS)
        n = cfg.products
        pre = rng.random(n) < 0.7
        created = np.where(
            pre,
            _random_times(rng, self.start_us - 2 * 365 * US_PER_DAY, self.start_us - US_PER_HOUR, n),
            _random_times(rng, self.start_us, self.end_us - US_PER_DAY, n),
        )
        created[0] = self.start_us - 2 * 365 * US_PER_DAY
        created.sort()

        # rozkład produktów po kategoriach: popularne kategorie mają więcej produktów
        leaf_weights = rng.lognormal(0, 0.5, len(ref.LEAVES))
        leaf = weighted_choice(rng, leaf_weights, n).astype(np.int16)
        top = LEAF_TOP[leaf]
        brand_start = np.array([s for s, _ in BRAND_RANGES])[top]
        brand_len = np.array([ln for _, ln in BRAND_RANGES])[top]
        noun_start = np.array([s for s, _ in NOUN_RANGES])[leaf]
        noun_len = np.array([ln for _, ln in NOUN_RANGES])[leaf]

        # sprzedawca musi istnieć w chwili dodania produktu
        k = np.searchsorted(self.sellers.joined_us, created, side="right")
        seller = sample_prefix(rng, self.sellers.cumw, np.maximum(k, 1))

        medians = np.array([c.leaf.median_eur for c in ref.LEAVES])[leaf]  # type: ignore[union-attr]
        sigmas = np.array([c.leaf.sigma for c in ref.LEAVES])[leaf]  # type: ignore[union-attr]
        base = np.maximum(1.0, rng.lognormal(np.log(medians), sigmas))
        base_cents = (np.ceil(base) * 100 - 1).astype(np.int64)  # ceny „,99”
        wkg = np.array([c.leaf.weight_kg for c in ref.LEAVES])[leaf]  # type: ignore[union-attr]
        weight_g = np.maximum(50, rng.lognormal(np.log(wkg * 1000), 0.3)).astype(np.int32)

        # do trzech zmian ceny w trakcie okresu (promocje, podwyżki)
        change_us = np.full((n, 3), NULL_TS, dtype=np.int64)
        change_factor = np.ones((n, 3), dtype=np.float64)
        n_changes = weighted_choice(rng, [0.55, 0.25, 0.13, 0.07], n)
        for j in range(3):
            has = n_changes > j
            change_us[has, j] = _random_times(rng, self.start_us, self.end_us, int(has.sum()))
            change_factor[has, j] = rng.choice(
                np.array([0.8, 0.85, 0.9, 0.95, 1.05, 1.1, 1.15]), int(has.sum())
            )
        change_us = np.where(
            change_us == NULL_TS, NULL_TS, np.maximum(change_us, created[:, None] + US_PER_HOUR)
        )
        change_us.sort(axis=1)  # NULL_TS (najmniejsza wartość) trafia na początek
        # przesuń NULL-e na koniec, żeby kolejność zmian była chronologiczna
        order = np.argsort(change_us == NULL_TS, axis=1, kind="stable")
        change_us = np.take_along_axis(change_us, order, axis=1)
        change_factor = np.take_along_axis(change_factor, order, axis=1)

        if cfg.skew > 0:
            ranks = rng.permutation(n) + 1
            weights = ranks.astype(np.float64) ** (-cfg.skew)
        else:
            weights = np.ones(n)
        return Products(
            n=n,
            created_us=created,
            leaf=leaf,
            seller=seller.astype(np.int32),
            brand=(brand_start + rng.integers(0, brand_len)).astype(np.int16),
            noun=(noun_start + rng.integers(0, noun_len)).astype(np.int16),
            model=rng.integers(10, 999, n).astype(np.int16),
            color=rng.integers(0, len(ref.COLORS), n).astype(np.int8),
            base_cents_eur=base_cents,
            weight_g=weight_g,
            change_us=change_us,
            change_factor=change_factor,
            cumw=np.cumsum(weights),
        )

    # -- anomalie ------------------------------------------------------------

    def _plan_anomalies(self) -> list[Anomaly]:
        cfg = self.cfg
        if not cfg.anomalies or cfg.days < 14:
            return []
        rng = rng_for(cfg.seed, Stream.ANOMALIES)
        lo, hi = cfg.days // 3, cfg.days - 3
        days = rng.choice(np.arange(lo, hi), size=4, replace=False)
        storm_hour = int(rng.integers(8, 20))
        popular = int(np.argmax(np.diff(np.concatenate([[0], self.products.cumw]))))
        seller_id = int(self.products.seller[popular]) + 1
        schema_day = int(cfg.days * 0.6)

        def iso(d: int) -> str:
            return self.dates[d].isoformat()

        return [
            Anomaly(
                "clickstream_android_drop",
                int(days[0]),
                iso(int(days[0])),
                "Błąd w wydaniu aplikacji Android: ok. 85% zdarzeń z Androida nie dotarło.",
                {"platform": "android", "drop_ratio": 0.85},
            ),
            Anomaly(
                "clickstream_retry_storm",
                int(days[1]),
                iso(int(days[1])),
                "Awaria kolektora zdarzeń: klienci ponawiali wysyłkę, liczba duplikatów wzrosła ~15x.",
                {"start_hour_utc": storm_hour, "duration_hours": 2, "duplicate_multiplier": 15},
            ),
            Anomaly(
                "order_items_price_in_minor_units",
                int(days[2]),
                iso(int(days[2])),
                "Błąd integracji sprzedawcy: unit_price w groszach zamiast w złotych (x100).",
                {"seller_id": seller_id},
            ),
            Anomaly(
                "partner_file_missing",
                int(days[3]),
                iso(int(days[3])),
                "Plik SpeedPost za ten dzień nie dotarł; jego zawartość dołączono do pliku z dnia następnego.",
                {"carrier": "speedpost"},
            ),
            Anomaly(
                "partner_schema_change",
                schema_day,
                iso(schema_day),
                "QuickShip bez zapowiedzi zmienił schemat pliku (zmiana nazwy kolumny, jednostki wagi, nowa kolumna).",
                {"carrier": "quickship"},
            ),
        ]

    def anomaly(self, kind: str) -> Anomaly | None:
        return next((a for a in self.anomalies if a.kind == kind), None)

    # -- zamówienia (cache) ---------------------------------------------------

    def orders_for_day(self, day: int) -> OrdersBatch:
        """Zamówienia z danego dnia. Wynik jest deterministyczny i trzymany w małym cache LRU."""
        from .orders import generate_orders

        if day in self._orders_cache:
            self._orders_cache.move_to_end(day)
            return self._orders_cache[day]
        batch = generate_orders(self, day)
        self._orders_cache[day] = batch
        if len(self._orders_cache) > self.ORDERS_CACHE_SIZE:
            self._orders_cache.popitem(last=False)
        return batch

    # -- napisy na żądanie ------------------------------------------------------

    def customer_profile(self, idx: np.ndarray, as_of_us: np.ndarray | int) -> dict[str, pa.Array]:
        """Dane osobowe klientów ``idx`` w stanie na moment ``as_of_us`` (uwzględnia zmiany i RODO)."""
        c = self.customers
        idx = np.asarray(idx, dtype=np.int64)
        as_of = np.broadcast_to(np.asarray(as_of_us, dtype=np.int64), idx.shape)
        g = c.gender[idx]
        first = take_strings(FIRST_POOL, c.first_idx[idx])
        last = pc.if_else(
            pa.array(g == 1),
            take_strings(LAST_POOL_F, c.last_idx[idx]),
            take_strings(LAST_POOL_M, c.last_idx[idx]),
        )

        email_changed = (c.email_change_us[idx] != NULL_TS) & (c.email_change_us[idx] <= as_of)
        num = np.where(email_changed, c.email2_num[idx], c.email_num[idx])
        dom = np.where(email_changed, c.email2_domain[idx], c.email_domain[idx])
        f_tok = take_strings([ref.email_token(x) for x in FIRST_POOL], c.first_idx[idx])
        l_tok = pc.if_else(
            pa.array(g == 1),
            take_strings([ref.email_token(x) for x in LAST_POOL_F], c.last_idx[idx]),
            take_strings([ref.email_token(x) for x in LAST_POOL_M], c.last_idx[idx]),
        )
        pattern = np.where(email_changed, (c.email_pattern[idx] + 1) % 4, c.email_pattern[idx])
        local = pc.choose(
            pa.array(pattern.astype(np.int8)),
            join(f_tok, ".", l_tok),
            join(f_tok, l_tok),
            join(pc.utf8_slice_codeunits(f_tok, 0, 1), ".", l_tok),
            join(l_tok, ".", f_tok),
        )
        num_str = pc.if_else(pa.array(num >= 0), int_to_str(num), pa.scalar("", pa.string()))
        email = join(local, num_str, "@", take_strings(DOMAIN_POOL, dom))

        moved = (c.move_us[idx] != NULL_TS) & (c.move_us[idx] <= as_of)
        city_i = np.where(moved, c.city2[idx], c.city[idx])
        street_i = np.where(moved, c.street2[idx], c.street[idx])
        house = np.where(moved, c.house2[idx], c.house[idx])
        apt = np.where(moved, c.apt2[idx], c.apt[idx])
        postal_raw = np.where(moved, c.postal2[idx], c.postal[idx])
        country = c.country[idx]

        apt_sep = np.array([x.apartment_sep for x in ref.COUNTRIES], dtype=object)[country]
        has_apt = (apt > 0) & (apt_sep != "")
        street = join(take_strings(STREET_POOL, street_i), " ", int_to_str(house))
        street = pc.if_else(
            pa.array(has_apt), join(street, pa.array(apt_sep.astype(str)), int_to_str(apt)), street
        )

        postal = self._postal_codes(country, city_i, postal_raw)
        phone_digits = np.array([x.phone_digits for x in ref.COUNTRIES])[country]
        phone_body = pc.utf8_slice_codeunits(digits_strings(c.phone_number[idx], 8), 0, 8)
        phone_body = _right_chars(phone_body, phone_digits)
        prefix = take_strings(PHONE_PREFIX_POOL, c.phone_prefix[idx])
        phone = pc.if_else(
            pa.array(c.phone_spaced[idx]), join(prefix, " ", phone_body), join(prefix, phone_body)
        )

        consent_flip = (c.consent_change_us[idx] != NULL_TS) & (c.consent_change_us[idx] <= as_of)
        consent = np.where(consent_flip, ~c.consent[idx], c.consent[idx])

        erased = (c.erased_us[idx] != NULL_TS) & (c.erased_us[idx] <= as_of)
        erased_arr = pa.array(erased)

        def pii(arr: pa.Array) -> pa.Array:
            return pc.if_else(erased_arr, pa.scalar(None, arr.type), arr)

        return {
            "first_name": pii(first),
            "last_name": pii(last),
            "email": pii(email),
            "phone": pii(phone),
            "birth_date": pii(pa.array(c.birth_day[idx], type=pa.int32()).cast(pa.date32())),
            "country": take_strings(ref.COUNTRY_CODES, country),
            "city": take_strings(CITY_POOL, city_i),
            "postal_code": pii(postal),
            "street_address": pii(street),
            "marketing_consent": pc.if_else(erased_arr, pa.scalar(False), pa.array(consent)),
            "is_erased": erased_arr,
        }

    def _postal_codes(self, country: np.ndarray, city_i: np.ndarray, raw: np.ndarray) -> pa.Array:
        prefix = take_strings(CITY_PREFIX, city_i)
        d4 = digits_strings(raw, 4)
        d3 = pc.utf8_slice_codeunits(d4, 0, 3)
        letters = np.array(list("ABCDEFGHJKLMNPRSTVWXZ"))
        two = pa.array(np.char.add(letters[raw % len(letters)], letters[(raw // 21) % len(letters)]))
        variants = {
            "P#-###": join(prefix, pc.utf8_slice_codeunits(d4, 0, 1), "-", d3),
            "P####": join(prefix, d4),
            "P## ##": join(prefix, pc.utf8_slice_codeunits(d4, 0, 2), " ", pc.utf8_slice_codeunits(d4, 2, 4)),
            "LT-P####": join("LT-", prefix, d4),
            "P### ??": join(prefix, d3, " ", two),
        }
        keys = list(variants)
        choice = np.array([keys.index(c.postal_format) for c in ref.COUNTRIES], dtype=np.int8)[country]
        return pc.choose(pa.array(choice), *variants.values())

    def seller_names(self, idx: np.ndarray) -> pa.Array:
        s = self.sellers
        idx = np.asarray(idx, dtype=np.int64)
        names = []
        for i in idx:
            code = ref.COUNTRY_CODES[s.country[i]]
            suffixes = ref.SELLER_SUFFIXES[code]
            names.append(f"{ref.SELLER_WORDS[s.word[i]]} {suffixes[s.suffix[i] % len(suffixes)]}")
        return pa.array(names, type=pa.string())

    def product_names(self, idx: np.ndarray) -> pa.Array:
        p = self.products
        idx = np.asarray(idx, dtype=np.int64)
        model = join(
            take_strings([chr(65 + i) for i in range(26)], (p.model[idx] % 26)),
            take_strings([chr(65 + i) for i in range(26)], (p.model[idx] // 26) % 26),
            "-",
            int_to_str(p.model[idx]),
        )
        return join(
            take_strings(BRAND_POOL, p.brand[idx]),
            " ",
            take_strings(NOUN_POOL, p.noun[idx]),
            " ",
            model,
            ", kolor ",
            take_strings(ref.COLORS, p.color[idx]),
        )

    def product_skus(self, idx: np.ndarray) -> pa.Array:
        idx = np.asarray(idx, dtype=np.int64)
        slugs = [c.slug[:3].upper() for c in ref.LEAVES]
        return join("NC-", take_strings(slugs, self.products.leaf[idx]), "-", digits_strings(idx + 1, 7))


def _right_chars(arr: pa.Array, widths: np.ndarray) -> pa.Array:
    """Ostatnie ``widths[i]`` znaków każdego napisu (napisy mają stałą długość 8)."""
    out = arr
    for w in np.unique(widths):
        mask = pa.array(widths == w)
        out = pc.if_else(mask, pc.utf8_slice_codeunits(arr, int(8 - w), 8), out)
    return out


def local_price_cents(eur_cents: np.ndarray, country: np.ndarray) -> np.ndarray:
    """Cena w walucie kraju, zaokrąglona „marketingowo” (x,99 albo …9 dla CZK)."""
    rate = COUNTRY_EUR_RATE[country]
    raw = eur_cents * rate
    is_czk = np.array([c.currency == "CZK" for c in ref.COUNTRIES])[country]
    marketing = np.ceil(raw / 100.0) * 100 - 1
    czk = np.ceil(raw / 1000.0) * 1000 - 100
    return np.where(is_czk, czk, marketing).astype(np.int64)
