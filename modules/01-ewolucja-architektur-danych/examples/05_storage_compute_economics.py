"""Ekonomia separacji storage i compute: trzy modele płatności za to samo obciążenie NovaCart.

Symulujemy rok (8760 godzin) zapytań analitycznych NovaCart i liczymy roczny koszt compute w modelach:

A. Stały klaster (appliance on-prem albo klaster MPP w chmurze włączony 24/7) — płacisz za pojemność,
   którą musisz dobrać do szczytu. A1 = rozmiar na szczyt, A2 = rozmiar na 90. percentyl (taniej,
   ale w godzinach szczytu zapytania czekają w kolejce).
B. Płatność za przeskanowane bajty (np. BigQuery on-demand) — płacisz za TiB odczytane przez zapytania.
C. Płatność za czas pracy compute z auto-suspend (np. wirtualny warehouse Snowflake, Databricks SQL
   serverless, BigQuery editions z autoscalingiem) — płacisz za sekundy pracy, compute skaluje się do zera.

UWAGA: ceny i przepustowości poniżej są PARAMETRAMI ILUSTRACYJNYMI rzędu wielkości, a nie cennikiem
konkretnego dostawcy. Celem jest pokazanie KSZTAŁTU kosztu (od czego zależy), a nie ranking platform.
Aktualne ceny sprawdzaj w cennikach (moduły 16, 31, 32, 39).

Uruchomienie (z katalogu examples/):
    env -u VIRTUAL_ENV uv run python 05_storage_compute_economics.py
    env -u VIRTUAL_ENV uv run python 05_storage_compute_economics.py --annual-tib 6000 50000
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np


@dataclass(frozen=True)
class Prices:
    # Jednostka obliczeniowa (CU) = „jeden węzeł” umownej wielkości.
    tib_per_cu_hour: float = 0.5  # ile TiB skanu przetwarza 1 CU w godzinę
    fixed_cu_hour_usd: float = 2.00  # CU w stałym klastrze (rezerwacja / amortyzacja sprzętu)
    elastic_cu_hour_usd: float = 3.00  # CU elastyczne, płatne za sekundy (premia za elastyczność)
    elastic_idle_overhead: float = 0.15  # +15% za minimalny czas naliczania i bezczynność przed auto-suspend
    on_demand_usd_per_tib: float = 6.25  # rząd wielkości ceny skanu on-demand (BigQuery US, 2026)


def hourly_profile(kind: str, annual_tib: float) -> np.ndarray:
    """Zapotrzebowanie w TiB skanu na każdą godzinę 2025 roku."""
    hours = np.arange(365 * 24)
    days = [date(2025, 1, 1) + timedelta(days=int(h // 24)) for h in hours[::24]]
    if kind == "stały":
        demand = np.ones(hours.size)
    else:
        hod = hours % 24
        # Dzień: nocny batch ELT (01–04 UTC), praca analityków (07–17), dashboardy wieczorem.
        daily = np.select(
            [(hod >= 1) & (hod < 4), (hod >= 7) & (hod < 17), (hod >= 17) & (hod < 21)],
            [6.0, 2.0, 0.8],
            default=0.15,
        )
        weekday = np.repeat([1.0 if d.weekday() < 5 else 0.35 for d in days], 24)
        month = np.repeat([1.4 if d.month == 12 else 1.15 if d.month == 11 else 1.0 for d in days], 24)
        # Tydzień Black Friday (24–30.11.2025): dodatkowe raporty i analizy ad hoc, ×3.
        bf = np.repeat([3.0 if date(2025, 11, 24) <= d <= date(2025, 11, 30) else 1.0 for d in days], 24)
        demand = daily * weekday * month * bf
    return demand / demand.sum() * annual_tib


def costs(demand: np.ndarray, p: Prices) -> dict[str, dict[str, float]]:
    cu_needed = demand / p.tib_per_cu_hour  # CU-godziny potrzebne w każdej godzinie
    total_cu_hours = cu_needed.sum()
    out: dict[str, dict[str, float]] = {}

    for label, size in (
        ("A1. stały klaster na szczyt", cu_needed.max()),
        ("A2. stały klaster na p90", np.percentile(cu_needed, 90)),
    ):
        nodes = max(1, math.ceil(size))
        overloaded = cu_needed > nodes
        # Praca, która nie zmieściła się w godzinie, czeka w kolejce (opóźnienie, nie dodatkowy koszt).
        out[label] = {
            "usd": nodes * p.fixed_cu_hour_usd * demand.size,
            "nodes": nodes,
            "util": total_cu_hours / (nodes * demand.size),
            "overload_h": int(overloaded.sum()),
        }
    out["B.  płatność za bajty (on-demand)"] = {
        "usd": demand.sum() * p.on_demand_usd_per_tib,
        "nodes": float("nan"),
        "util": 1.0,
        "overload_h": 0,
    }
    out["C.  compute za sekundy + auto-suspend"] = {
        "usd": total_cu_hours * (1 + p.elastic_idle_overhead) * p.elastic_cu_hour_usd,
        "nodes": float(np.ceil(cu_needed.max())),
        "util": 1 / (1 + p.elastic_idle_overhead),
        "overload_h": 0,
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--annual-tib",
        type=float,
        nargs="+",
        default=[1500, 20000],
        help="łączny skan w roku [TiB]; można podać kilka wartości",
    )
    args = parser.parse_args()
    p = Prices()

    for annual in args.annual_tib:
        print(
            f"=== Roczny skan: {annual:,.0f} TiB (~{annual / 365:,.1f} TiB/dzień), "
            f"1 CU = {p.tib_per_cu_hour} TiB/h ===\n"
        )
        for kind in ("stały", "realistyczny"):
            demand = hourly_profile(kind, annual)
            cu = demand / p.tib_per_cu_hour
            print(
                f"Profil „{kind}”: szczyt {cu.max():.2f} CU, p90 {np.percentile(cu, 90):.2f} CU, "
                f"średnio {cu.mean():.2f} CU, szczyt/średnia ×{cu.max() / cu.mean():.1f}"
            )
            print(
                f"  {'Model':40s} {'koszt/rok':>12s} {'węzły':>6s} {'wykorzystanie':>14s} "
                f"{'godz. w kolejce':>16s}"
            )
            for label, r in costs(demand, p).items():
                nodes = "—" if math.isnan(r["nodes"]) else f"{r['nodes']:.0f}"
                util = "—" if label.startswith("B") else f"{r['util']:.0%}"
                print(f"  {label:40s} {r['usd']:>10,.0f} $ {nodes:>6s} {util:>14s} {r['overload_h']:>16,}")
            print()

    # Próg opłacalności: elastyczny compute jest tańszy, gdy wykorzystanie stałego klastra < próg.
    breakeven = p.fixed_cu_hour_usd / (p.elastic_cu_hour_usd * (1 + p.elastic_idle_overhead))
    print(f"Próg opłacalności A vs C: stały klaster wygrywa dopiero przy wykorzystaniu > {breakeven:.0%}")
    print(
        f"Koszt 1 TiB przy 100% wykorzystaniu: A {p.fixed_cu_hour_usd / p.tib_per_cu_hour:.2f} $, "
        f"C {p.elastic_cu_hour_usd * (1 + p.elastic_idle_overhead) / p.tib_per_cu_hour:.2f} $, "
        f"B {p.on_demand_usd_per_tib:.2f} $"
    )


if __name__ == "__main__":
    main()
