"""Model skalowania czterech architektur przetwarzania równoległego.

Lekcja 01.07. Prosty model analityczny (nie benchmark!). Liczy czas zapytania analitycznego
(skan + filtr + join z redystrybucją) dla shared-memory, shared-disk, shared-nothing
i shared-data przy rosnącej liczbie węzłów, a potem:
  - jak przepustowość sieci i trafienia w cache decydują o opłacalności shared-data,
  - ile danych trzeba przenieść przy dodaniu węzła,
  - ile węzło-godzin kosztuje klaster, który nie może się „wyłączyć”.

Wszystkie parametry są jawne (sekcja PARAMETRY). Zmień je i obserwuj, jak przesuwa się
wąskie gardło — to jest właściwa lekcja, a nie konkretne liczby.

Uruchomienie: cd examples && uv run python 08_parallel_architectures_sim.py
"""

from __future__ import annotations

import bisect
import hashlib

# --- PARAMETRY (rzędy wielkości, nie pomiary konkretnego sprzętu) -------------------------------
DATA_GB = 1_000  # zapytanie czyta 1 TB (po kompresji)
CPU_GBPS = 0.5  # ile GB/s jeden węzeł potrafi zdekompresować i przefiltrować
SHUFFLE_FRACTION = 0.2  # jaka część przeczytanych danych przechodzi przez join/agregację z redystrybucją
SKEW = 1.25  # najwolniejszy węzeł ma 25% więcej pracy niż średnia (data skew)

SMP_MAX_NODES = 64  # shared-memory: jedna maszyna, max 64 „jednostki” (np. 2 × 32 rdzenie)
SMP_STORAGE_GBPS = 12  # lokalne NVMe jednej maszyny
SMP_COHERENCE = 0.004  # koszt spójności cache na każdą dodatkową jednostkę

SAN_GBPS = 8  # shared-disk: wspólna macierz/SAN, przepustowość łączna
LOCK_PENALTY = 0.03  # shared-disk: koszt globalnego lock managera / cache fusion na węzeł przy zapisach
WRITE_SHARE = 0.2  # udział operacji modyfikujących w obciążeniu mieszanym

LOCAL_DISK_GBPS = 2.0  # shared-nothing: lokalne dyski jednego węzła
NET_GBPS = 12.5  # sieć na węzeł: 100 Gb/s ≈ 12,5 GB/s (centrum danych chmury)
OBJECT_PER_NODE_GBPS = 6.0  # shared-data: realnie osiągalny odczyt z object storage na węzeł
CACHE_GBPS = 4.0  # shared-data: lokalny cache SSD węzła
REBALANCE_GBPS = 0.5  # migracja danych na węzeł; dławiona, żeby nie zabić bieżących zapytań

NODES = [1, 2, 4, 8, 16, 32, 64, 128]


def shuffle_s(n: int, net_gbps: float = NET_GBPS) -> float:
    """Redystrybucja: (n-1)/n danych opuszcza węzeł; wszystkie węzły wysyłają równolegle."""
    return 0.0 if n == 1 else SHUFFLE_FRACTION * DATA_GB * (n - 1) / n / (n * net_gbps)


def shared_memory(n: int, write_share: float = 0.0) -> float | None:
    if n > SMP_MAX_NODES:
        return None  # nie da się kupić większej obudowy
    rate = min(n * CPU_GBPS, SMP_STORAGE_GBPS) / (1 + SMP_COHERENCE * (n - 1))
    return DATA_GB / rate  # join w pamięci wspólnej: brak redystrybucji przez sieć


def shared_disk(n: int, write_share: float = 0.0) -> float:
    rate = min(n * CPU_GBPS, SAN_GBPS) / (1 + LOCK_PENALTY * write_share * 10 * (n - 1))
    return DATA_GB / rate + shuffle_s(n)


def shared_nothing(n: int, write_share: float = 0.0) -> float:
    per_node = min(CPU_GBPS, LOCAL_DISK_GBPS)
    return SKEW * DATA_GB / (n * per_node) + shuffle_s(n) if n > 1 else DATA_GB / per_node


def shared_data(
    n: int, write_share: float = 0.0, hit: float = 0.8, net: float = OBJECT_PER_NODE_GBPS
) -> float:
    io = 1 / (hit / CACHE_GBPS + (1 - hit) / net)
    per_node = min(CPU_GBPS, io)
    # Systemy shared-data dzielą pracę dynamicznie (małe porcje, work stealing), więc skew jest mniejszy.
    skew = 1.05 if n > 1 else 1.0
    return skew * DATA_GB / (n * per_node) + shuffle_s(n)


def fmt(t: float | None) -> str:
    return "     —" if t is None else f"{t:6.0f}"


def table_scaling() -> None:
    archs = [
        ("shared-memory", shared_memory),
        ("shared-disk", shared_disk),
        ("shared-nothing", shared_nothing),
        ("shared-data", shared_data),
    ]
    for title, ws in (
        ("tylko odczyt (analityka)", 0.0),
        (f"obciążenie mieszane, {WRITE_SHARE:.0%} zapisów", WRITE_SHARE),
    ):
        print(f"\n[1] Czas zapytania [s] dla {DATA_GB} GB — {title}")
        print(f"    {'węzły':>6} " + " ".join(f"{a:>15}" for a, _ in archs))
        for n in NODES:
            print(f"    {n:>6} " + " ".join(f"{fmt(f(n, ws)):>15}" for _, f in archs))
    print("\n    Przyspieszenie przy 64 węzłach względem 1 węzła (tylko odczyt):")
    for a, f in archs:
        print(f"      {a:<15} ×{f(1) / f(64):5.1f}")


def table_network() -> None:
    print("\n[2] Shared-data: przepustowość I/O węzła [GB/s] vs sieć i trafienia w cache")
    print(
        "    (węzeł przetwarza max", CPU_GBPS, "GB/s — powyżej tej wartości I/O przestaje być wąskim gardłem)"
    )
    nets = [
        ("1 Gb/s (2008)", 0.125 * 0.7),
        ("10 Gb/s (2014)", 1.25 * 0.7),
        ("100 Gb/s (dziś)", OBJECT_PER_NODE_GBPS),
    ]
    print(f"    {'cache hit':>9} " + " ".join(f"{n:>16}" for n, _ in nets))
    for hit in (0.0, 0.5, 0.8, 0.95):
        row = [1 / (hit / CACHE_GBPS + (1 - hit) / bw) if hit < 1 else CACHE_GBPS for _, bw in nets]
        print(f"    {hit:>9.0%} " + " ".join(f"{r:>16.2f}" for r in row))


def moved_fraction(old: int, new: int, keys: int = 200_000) -> tuple[float, float]:
    """Jaka część kluczy zmienia węzeł: hash mod N vs consistent hashing (100 vnode'ów na węzeł)."""

    def h(s: str) -> int:
        return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")

    def ring(n: int) -> list[tuple[int, int]]:
        return sorted((h(f"node{i}-v{v}"), i) for i in range(n) for v in range(100))

    r_old, r_new = ring(old), ring(new)
    pos_old, pos_new = [p for p, _ in r_old], [p for p, _ in r_new]
    mod_moved = ring_moved = 0
    for k in range(keys):
        x = h(f"key{k}")
        mod_moved += (x % old) != (x % new)
        a = r_old[bisect.bisect(pos_old, x) % len(r_old)][1]
        b = r_new[bisect.bisect(pos_new, x) % len(r_new)][1]
        ring_moved += a != b
    return mod_moved / keys, ring_moved / keys


def table_rebalance(total_tb: float = 100) -> None:
    print(f"\n[3] Dodanie węzłów do klastra shared-nothing z {total_tb:.0f} TB danych")
    print(
        f"    (migracja {REBALANCE_GBPS} GB/s na węzeł; w shared-data przenosi się 0 B, tylko cache się „rozgrzewa”)"
    )
    print(
        f"    {'zmiana':>8} {'minimum':>9} {'hash mod N':>11} {'consistent':>11} {'czas mod N':>11} {'czas consistent':>16}"
    )
    for old, new in ((8, 9), (8, 16), (16, 17)):
        mod, ring = moved_fraction(old, new)
        minimum = (new - old) / new

        def hours(frac: float, old: int = old) -> float:
            return frac * total_tb * 1000 / (old * REBALANCE_GBPS) / 3600

        print(
            f"    {old:>3}→{new:<4} {minimum:>9.1%} {mod:>11.1%} {ring:>11.1%}"
            f" {hours(mod):>9.1f} h {hours(ring):>14.1f} h"
        )


def table_idle_cost() -> None:
    print("\n[4] Węzło-godziny w miesiącu: klaster 16 węzłów, obciążenie 6 h dziennie")
    always_on = 16 * 24 * 30
    on_demand = 16 * 6 * 30
    print(f"    shared-nothing (dane na węzłach, klaster musi działać): {always_on:>6} węzło-h")
    print(
        f"    shared-data (compute wyłączany poza pracą):             {on_demand:>6} węzło-h"
        f"  (×{always_on / on_demand:.0f} mniej + koszt storage)"
    )


if __name__ == "__main__":
    table_scaling()
    table_network()
    table_rebalance()
    table_idle_cost()
