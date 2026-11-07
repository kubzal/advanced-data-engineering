"""Wektoryzowane narzędzia: deterministyczne RNG, UUID, kwoty pieniężne, znaczniki czasu.

Generator unika pętli w Pythonie po wierszach: wszystko jest liczone na tablicach numpy
i zamieniane na kolumny Arrow. Dzięki temu skala L/XL jest osiągalna na zwykłej maszynie.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

US_PER_SECOND = 1_000_000
US_PER_MINUTE = 60 * US_PER_SECOND
US_PER_HOUR = 60 * US_PER_MINUTE
US_PER_DAY = 24 * US_PER_HOUR
NULL_TS = np.iinfo(np.int64).min  # wartownik dla "brak znacznika czasu"

TS_TYPE = pa.timestamp("us", tz="UTC")
MONEY_TYPE = pa.decimal128(12, 2)


class Stream(IntEnum):
    """Niezależne strumienie losowości. Każdy (stream, klucz) ma własny, stały seed."""

    CUSTOMERS = 1
    SELLERS = 2
    PRODUCTS = 3
    CALENDAR = 4
    ANOMALIES = 5
    ORDERS = 10
    CLICKSTREAM = 11
    LOGISTICS = 12
    PARTNER_FILES = 13
    PAYMENTS = 14
    DOCUMENTS = 20
    STREAM = 30


def rng_for(seed: int, stream: Stream, *keys: int) -> np.random.Generator:
    """Deterministyczny generator dla danego strumienia i kluczy (np. numeru dnia)."""
    return np.random.default_rng([int(seed), int(stream), *(int(k) for k in keys)])


# ---------------------------------------------------------------------------
# Losowanie
# ---------------------------------------------------------------------------


def weighted_choice(rng: np.random.Generator, weights: Sequence[float] | np.ndarray, n: int) -> np.ndarray:
    w = np.asarray(weights, dtype=np.float64)
    cdf = np.cumsum(w)
    cdf /= cdf[-1]
    return np.searchsorted(cdf, rng.random(n), side="right").clip(0, len(w) - 1)


def sample_prefix(rng: np.random.Generator, cumw: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Losuje indeksy z wagami, ale tylko spośród pierwszych ``k[i]`` elementów.

    Służy do zachowania spójności czasowej: elementy (klienci, produkty) są posortowane
    po dacie utworzenia, a ``k`` to liczba elementów istniejących w momencie zdarzenia.
    """
    k = np.asarray(k, dtype=np.int64)
    if (k < 1).any():
        raise ValueError("Każde zdarzenie musi mieć co najmniej jeden dostępny element")
    total = cumw[k - 1]
    u = rng.random(len(k)) * total
    idx = np.searchsorted(cumw, u, side="right")
    return np.minimum(idx, k - 1)


def per_row_choice(rng: np.random.Generator, probs: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Losowanie kategorii, gdzie rozkład zależy od grupy wiersza (np. metoda płatności od kraju).

    ``probs`` ma kształt (liczba_grup, liczba_kategorii).
    """
    cdf = np.cumsum(probs, axis=1)
    cdf /= cdf[:, -1:]
    u = rng.random(len(groups))
    rows = cdf[groups]
    return (u[:, None] >= rows).sum(axis=1).clip(0, probs.shape[1] - 1)


def segment_positions(lengths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Dla segmentów o długościach ``lengths`` zwraca (indeks_segmentu, pozycja_w_segmencie)."""
    lengths = np.asarray(lengths, dtype=np.int64)
    seg = np.repeat(np.arange(len(lengths)), lengths)
    starts = np.cumsum(lengths) - lengths
    pos = np.arange(len(seg)) - np.repeat(starts, lengths)
    return seg, pos


# ---------------------------------------------------------------------------
# Identyfikatory
# ---------------------------------------------------------------------------

_HEX = np.frombuffer(b"0123456789abcdef", dtype=np.uint8)
_B36 = np.frombuffer(b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ", dtype=np.uint8)


def ascii_matrix_to_arrow(mat: np.ndarray) -> pa.StringArray:
    """Zamienia macierz (n, w) bajtów ASCII na kolumnę Arrow z n napisami długości w (zero-copy)."""
    mat = np.ascontiguousarray(mat, dtype=np.uint8)
    n, w = mat.shape
    offsets = np.arange(n + 1, dtype=np.int64) * w
    if offsets[-1] < np.iinfo(np.int32).max:
        return pa.Array.from_buffers(
            pa.string(), n, [None, pa.py_buffer(offsets.astype(np.int32)), pa.py_buffer(mat)]
        )
    large = pa.Array.from_buffers(pa.large_string(), n, [None, pa.py_buffer(offsets), pa.py_buffer(mat)])
    return large.cast(pa.string())


def _bytes_to_uuid_strings(b: np.ndarray) -> pa.StringArray:
    n = b.shape[0]
    hexed = np.empty((n, 32), dtype=np.uint8)
    hexed[:, 0::2] = _HEX[b >> 4]
    hexed[:, 1::2] = _HEX[b & 0x0F]
    out = np.full((n, 36), ord("-"), dtype=np.uint8)
    out[:, 0:8] = hexed[:, 0:8]
    out[:, 9:13] = hexed[:, 8:12]
    out[:, 14:18] = hexed[:, 12:16]
    out[:, 19:23] = hexed[:, 16:20]
    out[:, 24:36] = hexed[:, 20:32]
    return ascii_matrix_to_arrow(out)


def uuid4_strings(rng: np.random.Generator, n: int) -> pa.StringArray:
    """n losowych UUID w wersji 4, w formacie tekstowym."""
    b = rng.integers(0, 256, size=(n, 16), dtype=np.uint8)
    b[:, 6] = (b[:, 6] & 0x0F) | 0x40
    b[:, 8] = (b[:, 8] & 0x3F) | 0x80
    return _bytes_to_uuid_strings(b)


def splitmix64(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.uint64)
    with np.errstate(over="ignore"):
        z = x + np.uint64(0x9E3779B97F4A7C15)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return z ^ (z >> np.uint64(31))


def hashed_uuid_strings(keys: np.ndarray, salt: int) -> pa.StringArray:
    """Deterministyczny UUID wyliczony z klucza (np. stały identyfikator urządzenia klienta)."""
    keys = np.asarray(keys, dtype=np.uint64)
    with np.errstate(over="ignore"):
        h1 = splitmix64(keys ^ np.uint64(salt))
        h2 = splitmix64(h1 + np.uint64(1))
    b = np.stack([h1, h2], axis=1).view(np.uint8).reshape(-1, 16).copy()
    b[:, 6] = (b[:, 6] & 0x0F) | 0x40
    b[:, 8] = (b[:, 8] & 0x3F) | 0x80
    return _bytes_to_uuid_strings(b)


def random_hex_strings(rng: np.random.Generator, n: int, length: int, prefix: str = "") -> pa.StringArray:
    b = rng.integers(0, 16, size=(n, length), dtype=np.uint8)
    body = ascii_matrix_to_arrow(_HEX[b])
    return pc.binary_join_element_wise(prefix, body, "") if prefix else body


def digits_strings(values: np.ndarray, width: int) -> pa.StringArray:
    """Liczby całkowite jako napisy o stałej szerokości z wiodącymi zerami."""
    values = np.asarray(values, dtype=np.int64)
    mat = np.empty((len(values), width), dtype=np.uint8)
    v = values.copy()
    for i in range(width - 1, -1, -1):
        mat[:, i] = ord("0") + (v % 10)
        v //= 10
    return ascii_matrix_to_arrow(mat)


def base36_strings(values: np.ndarray, width: int) -> pa.StringArray:
    values = np.asarray(values, dtype=np.int64)
    mat = np.empty((len(values), width), dtype=np.uint8)
    v = values.copy()
    for i in range(width - 1, -1, -1):
        mat[:, i] = _B36[v % 36]
        v //= 36
    return ascii_matrix_to_arrow(mat)


# ---------------------------------------------------------------------------
# Konwersje do Arrow
# ---------------------------------------------------------------------------


def money(
    cents: np.ndarray, null_mask: np.ndarray | None = None, type_: pa.DataType = MONEY_TYPE
) -> pa.Array:
    """Kwota w groszach/centach (int64) → dokładny DECIMAL(12, 2), bez błędów float."""
    cents = np.ascontiguousarray(cents, dtype=np.int64)
    words = np.empty((len(cents), 2), dtype=np.int64)
    words[:, 0] = cents
    words[:, 1] = np.where(cents < 0, -1, 0)
    arr = pa.Array.from_buffers(type_, len(cents), [None, pa.py_buffer(words)])
    return with_nulls(arr, null_mask)


def ts(us: np.ndarray) -> pa.Array:
    """Mikrosekundy od epoki (z ``NULL_TS`` jako brakiem wartości) → TIMESTAMP(us, UTC)."""
    us = np.asarray(us, dtype=np.int64)
    mask = us == NULL_TS
    return pa.array(us, type=pa.int64(), mask=mask if mask.any() else None).cast(TS_TYPE)


def nullable(values: np.ndarray, null_mask: np.ndarray | None, type_: pa.DataType) -> pa.Array:
    mask = None if null_mask is None or not np.any(null_mask) else np.asarray(null_mask)
    return pa.array(values, type=type_, mask=mask)


def with_nulls(arr: pa.Array, null_mask: np.ndarray | None) -> pa.Array:
    if null_mask is None or not np.any(null_mask):
        return arr
    return pc.if_else(pa.array(np.asarray(null_mask, dtype=bool)), pa.scalar(None, arr.type), arr)


def take_strings(pool: Sequence[str | None], idx: np.ndarray) -> pa.Array:
    """Wybiera napisy ze słownika po indeksach (szybciej niż budowanie listy w Pythonie)."""
    return pa.array(list(pool), type=pa.string()).take(pa.array(np.asarray(idx, dtype=np.int64)))


def int_to_str(values: np.ndarray) -> pa.Array:
    return pc.cast(pa.array(np.asarray(values, dtype=np.int64)), pa.string())


def join(*parts: pa.Array | str, sep: str = "") -> pa.Array:
    return pc.binary_join_element_wise(*parts, sep)


def clip_after(us: np.ndarray, limit_us: int) -> np.ndarray:
    """Zdarzenia po ``limit_us`` jeszcze się nie wydarzyły → NULL_TS."""
    out = np.asarray(us, dtype=np.int64).copy()
    out[(out > limit_us) & (out != NULL_TS)] = NULL_TS
    return out
