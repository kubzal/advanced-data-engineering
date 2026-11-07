"""Tabele wymiarów (klienci, sprzedawcy, produkty, kategorie) w stanie na dowolny moment.

Te same funkcje budują migawkę na koniec okresu (komponent ``entities``) oraz obrazy
wierszy ``before``/``after`` w strumieniu CDC, więc oba źródła są ze sobą spójne.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa

from . import reference as ref
from .arrays import NULL_TS, US_PER_DAY, US_PER_HOUR, Stream, money, rng_for, take_strings, ts
from .world import BRAND_POOL, CITY_POOL, LEAF_CATEGORY_ID

if TYPE_CHECKING:
    from .world import World


def _last_change(as_of: np.ndarray, base: np.ndarray, *changes: np.ndarray) -> np.ndarray:
    out = base.copy()
    for ch in changes:
        happened = (ch != NULL_TS) & (ch <= as_of)
        out = np.where(happened & (ch > out), ch, out)
    return out


def customers_columns(world: World, idx: np.ndarray, as_of: np.ndarray | int) -> dict[str, pa.Array]:
    c = world.customers
    idx = np.asarray(idx, dtype=np.int64)
    as_of_arr = np.broadcast_to(np.asarray(as_of, dtype=np.int64), idx.shape)
    prof = world.customer_profile(idx, as_of_arr)
    erased = c.erased_us[idx].copy()
    erased[(erased == NULL_TS) | (erased > as_of_arr)] = NULL_TS
    updated = _last_change(
        as_of_arr,
        c.signup_us[idx],
        c.email_change_us[idx],
        c.move_us[idx],
        c.consent_change_us[idx],
        c.erased_us[idx],
    )
    return {
        "customer_id": pa.array(idx + 1),
        "first_name": prof["first_name"],
        "last_name": prof["last_name"],
        "email": prof["email"],
        "phone": prof["phone"],
        "birth_date": prof["birth_date"],
        "country": prof["country"],
        "city": prof["city"],
        "postal_code": prof["postal_code"],
        "street_address": prof["street_address"],
        "marketing_consent": prof["marketing_consent"],
        "created_at": ts(c.signup_us[idx]),
        "updated_at": ts(updated),
        "gdpr_erased_at": ts(erased),
    }


def sellers_columns(world: World, idx: np.ndarray) -> dict[str, pa.Array]:
    s = world.sellers
    idx = np.asarray(idx, dtype=np.int64)
    return {
        "seller_id": pa.array(idx + 1),
        "name": world.seller_names(idx),
        "country": take_strings(ref.COUNTRY_CODES, s.country[idx]),
        "city": take_strings(CITY_POOL, s.city[idx]),
        "tier": take_strings(ref.SELLER_TIERS, s.tier[idx]),
        "rating": pa.array(s.rating[idx], type=pa.float64()),
        "commission_rate": money(s.commission_bp[idx], type_=pa.decimal128(5, 2)),
        "joined_at": ts(s.joined_us[idx]),
    }


def products_columns(world: World, idx: np.ndarray, as_of: np.ndarray | int) -> dict[str, pa.Array]:
    p = world.products
    idx = np.asarray(idx, dtype=np.int64)
    as_of_arr = np.broadcast_to(np.asarray(as_of, dtype=np.int64), idx.shape)
    updated = _last_change(as_of_arr, p.created_us[idx], *(p.change_us[idx, j] for j in range(3)))
    return {
        "product_id": pa.array(idx + 1),
        "sku": world.product_skus(idx),
        "name": world.product_names(idx),
        "category_id": pa.array(LEAF_CATEGORY_ID[p.leaf[idx]], type=pa.int32()),
        "seller_id": pa.array(p.seller[idx].astype(np.int64) + 1),
        "brand": take_strings(BRAND_POOL, p.brand[idx]),
        "list_price_eur": money(p.price_eur_cents_at(idx, as_of_arr)),
        "weight_g": pa.array(p.weight_g[idx], type=pa.int32()),
        "created_at": ts(p.created_us[idx]),
        "updated_at": ts(updated),
    }


def categories_table() -> pa.Table:
    cats = ref.FLAT_CATEGORIES
    return pa.table(
        {
            "category_id": pa.array([c.category_id for c in cats], type=pa.int32()),
            "parent_category_id": pa.array([c.parent_id for c in cats], type=pa.int32()),
            "slug": [c.slug for c in cats],
            "name_pl": [c.name_pl for c in cats],
            "name_en": [c.name_en for c in cats],
        }
    )


def gdpr_requests_table(world: World) -> pa.Table:
    """Wnioski o usunięcie danych (RODO), zrealizowane w bazie transakcyjnej."""
    c = world.customers
    idx = np.nonzero((c.erased_us != NULL_TS) & (c.erased_us <= world.end_us))[0]
    rng = rng_for(world.cfg.seed, Stream.CUSTOMERS, 99)
    lag = rng.integers(US_PER_HOUR, 25 * US_PER_DAY, len(idx))
    requested = np.maximum(c.erased_us[idx] - lag, np.maximum(c.signup_us[idx], world.start_us))
    return pa.table(
        {
            "request_id": pa.array(np.arange(1, len(idx) + 1, dtype=np.int64)),
            "customer_id": pa.array(idx + 1),
            "requested_at": ts(requested),
            "completed_at": ts(c.erased_us[idx]),
            "channel": take_strings(("email", "web_form", "customer_service"), rng.integers(0, 3, len(idx))),
        }
    )


def entity_tables(world: World) -> dict[str, pa.Table]:
    """Migawka wymiarów na koniec okresu (tak jak pełny eksport z bazy transakcyjnej)."""
    end = world.end_us
    c, s, p = world.customers, world.sellers, world.products
    cust_idx = np.nonzero(c.signup_us <= end)[0]
    sel_idx = np.nonzero(s.joined_us <= end)[0]
    prod_idx = np.nonzero(p.created_us <= end)[0]
    return {
        "customers": pa.table(customers_columns(world, cust_idx, end)),
        "sellers": pa.table(sellers_columns(world, sel_idx)),
        "products": pa.table(products_columns(world, prod_idx, end)),
        "categories": categories_table(),
        "gdpr_requests": gdpr_requests_table(world),
    }
