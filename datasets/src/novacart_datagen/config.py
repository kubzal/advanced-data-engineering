"""Konfiguracja generatora i presety skali."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ScalePreset:
    name: str
    customers: int
    products: int
    sellers: int
    days: int
    orders_per_day: int  # bazowa liczba zamówień dziennie na początku okresu
    description: str


SCALES: dict[str, ScalePreset] = {
    "xs": ScalePreset("xs", 2_000, 500, 40, 21, 80, "Testy jednostkowe i CI. Generuje się w kilka sekund."),
    "s": ScalePreset(
        "s",
        20_000,
        4_000,
        250,
        61,
        300,
        "Nauka i eksperymenty lokalne (DuckDB, laptop). Okres listopad–grudzień.",
    ),
    "m": ScalePreset(
        "m", 200_000, 30_000, 1_500, 365, 1_500, "Większość zadań w chmurze. Cały rok sprzedaży."
    ),
    "l": ScalePreset(
        "l",
        2_000_000,
        200_000,
        8_000,
        730,
        10_000,
        "Zadania wydajnościowe (BigQuery, Spark, Dataflow). Dwa lata.",
    ),
    "xl": ScalePreset(
        "xl",
        10_000_000,
        1_000_000,
        30_000,
        1_095,
        60_000,
        "Benchmarki i testy skali. Setki GB, generuj bezpośrednio do GCS.",
    ),
}

DEFAULT_END_DATE = date(2025, 12, 31)

ALL_COMPONENTS = ("entities", "orders", "clickstream", "partners", "cdc", "documents")
DEFAULT_COMPONENTS = ("entities", "orders", "clickstream", "partners")


@dataclass(frozen=True)
class Config:
    """Pełna, rozwiązana konfiguracja generatora.

    Te same wartości (łącznie z ``seed``) zawsze dają identyczne dane, niezależnie od liczby
    procesów roboczych. To ważne: rozwiązania zadań mogą odwoływać się do konkretnych liczb.
    """

    scale: str = "s"
    seed: int = 42
    start_date: date = date(2025, 11, 1)
    days: int = 61
    customers: int = 20_000
    products: int = 4_000
    sellers: int = 250
    orders_per_day: int = 300

    # Zachowanie użytkowników
    conversion_rate: float = 0.05  # odsetek sesji kończących się zakupem
    skew: float = 1.1  # wykładnik rozkładu Zipfa dla popularności produktów (0 = brak skośności)
    growth_per_year: float = 0.35  # roczny wzrost liczby zamówień

    # Jakość danych (świadomie wprowadzane problemy)
    duplicate_rate: float = 0.01  # odsetek zdarzeń clickstream wysłanych ponownie (te same event_id)
    late_rate: float = 0.03  # odsetek sesji mobilnych wysłanych z opóźnieniem (tryb offline)
    max_lateness_hours: float = 72.0  # maksymalne opóźnienie zdarzenia
    clock_skew_rate: float = 0.005  # odsetek sesji z rozjechanym zegarem urządzenia
    invalid_rate: float = 0.002  # odsetek uszkodzonych rekordów
    anomalies: bool = True  # czy wstrzykiwać anomalie (opisane w _manifest.json)

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(days=self.days - 1)

    @classmethod
    def from_scale(
        cls,
        scale: str = "s",
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        **overrides: object,
    ) -> Config:
        """Buduje konfigurację z presetu skali i opcjonalnych nadpisań.

        Domyślnie okres kończy się ``DEFAULT_END_DATE`` (31.12.2025), dzięki czemu każda skala
        obejmuje Black Friday i okres świąteczny.
        """
        if scale not in SCALES:
            raise ValueError(f"Nieznana skala {scale!r}. Dostępne: {', '.join(SCALES)}")
        preset = SCALES[scale]
        overrides = {k: v for k, v in overrides.items() if v is not None}
        days = int(overrides.pop("days", preset.days))
        if start_date is None:
            end = end_date or DEFAULT_END_DATE
            start_date = end - timedelta(days=days - 1)
        elif end_date is not None:
            days = (end_date - start_date).days + 1
        if days < 1:
            raise ValueError("Okres musi obejmować co najmniej jeden dzień")
        base = dict(
            scale=scale,
            start_date=start_date,
            days=days,
            customers=preset.customers,
            products=preset.products,
            sellers=preset.sellers,
            orders_per_day=preset.orders_per_day,
        )
        base.update(overrides)
        cfg = cls(**base)  # type: ignore[arg-type]
        cfg.validate()
        return cfg

    def validate(self) -> None:
        for name in ("conversion_rate", "duplicate_rate", "late_rate", "clock_skew_rate", "invalid_rate"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} musi być w przedziale [0, 1], jest {value}")
        if self.conversion_rate == 0:
            raise ValueError("conversion_rate musi być > 0")
        for name in ("customers", "products", "sellers", "orders_per_day"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} musi być >= 1")
        if self.skew < 0:
            raise ValueError("skew musi być >= 0")

    def to_dict(self) -> dict[str, object]:
        d = dataclasses.asdict(self)
        d["start_date"] = self.start_date.isoformat()
        d["end_date"] = self.end_date.isoformat()
        return d
