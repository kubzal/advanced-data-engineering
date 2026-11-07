"""Dokumenty nieustrukturyzowane dla modułów o RAG i danych dla AI (moduł 42).

* ``documents/products/product_descriptions.jsonl`` — opisy najpopularniejszych produktów,
* ``documents/policies/*.md`` — regulaminy NovaCart w kilku wersjach (z front matter:
  ``doc_id``, ``version``, ``valid_from``, ``valid_to``), co pozwala ćwiczyć przyrostowe
  odświeżanie indeksu i filtrowanie po metadanych.

Reguły biznesowe w dokumentach (progi darmowej dostawy, metody płatności, terminy zwrotów)
są zgodne z regułami użytymi do wygenerowania danych transakcyjnych.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np

from . import reference as ref
from .arrays import Stream, rng_for
from .entities import products_columns

if TYPE_CHECKING:
    from .world import World

MAX_PRODUCT_DOCS = 2_000

_INTROS = (
    "{name} to propozycja marki {brand} dla osób, które szukają produktu z kategorii {category} "
    "bez kompromisów.",
    "Poznaj {name}: jeden z najczęściej wybieranych produktów w kategorii {category} na NovaCart.",
    "{brand} przygotował {name} z myślą o codziennym użytkowaniu i trwałości na lata.",
)
_CLOSINGS = (
    "Produkt wysyła sprzedawca {seller_hint}; czas przygotowania przesyłki zwykle nie przekracza jednego dnia roboczego.",
    "Jeśli produkt nie spełni Twoich oczekiwań, możesz go zwrócić zgodnie z aktualną polityką zwrotów NovaCart.",
    "Opinie klientów podkreślają przede wszystkim stosunek jakości do ceny.",
)


def product_descriptions(world: World) -> bytes:
    p = world.products
    rng = rng_for(world.cfg.seed, Stream.DOCUMENTS, 1)
    weights = np.diff(np.concatenate([[0.0], p.cumw]))
    exists = p.created_us <= world.end_us
    top = np.argsort(-np.where(exists, weights, -1))[: min(MAX_PRODUCT_DOCS, int(exists.sum()))]
    top.sort()
    cols = products_columns(world, top, world.end_us)
    names = cols["name"].to_pylist()
    brands = cols["brand"].to_pylist()
    skus = cols["sku"].to_pylist()
    prices = cols["list_price_eur"].to_pylist()
    lines = []
    for i, pi in enumerate(top):
        leaf = ref.LEAVES[p.leaf[pi]]
        topcat = ref.CATEGORIES[leaf.top_index]
        feats = rng.choice(len(topcat.features), size=min(3, len(topcat.features)), replace=False)
        fmt = {
            "name": names[i],
            "brand": brands[i],
            "category": leaf.name_pl.lower(),
            "seller_hint": "z magazynu w " + ref.COUNTRIES[world.sellers.country[p.seller[pi]]].name_pl,
        }
        intro = _INTROS[rng.integers(0, len(_INTROS))].format(**fmt)
        bullets = "\n".join(f"- {topcat.features[f]}" for f in feats)
        closing = _CLOSINGS[rng.integers(0, len(_CLOSINGS))].format(**fmt)
        text = (
            f"{intro}\n\nNajważniejsze cechy:\n{bullets}\n\n"
            f"Specyfikacja: marka {brands[i]}, kod SKU {skus[i]}, waga {p.weight_g[pi] / 1000:.2f} kg, "
            f"kolor {ref.COLORS[p.color[pi]]}.\n\n{closing}"
        )
        lines.append(
            json.dumps(
                {
                    "product_id": int(pi) + 1,
                    "sku": skus[i],
                    "title": names[i],
                    "category": leaf.name_pl,
                    "brand": brands[i],
                    "list_price_eur": str(prices[i]),
                    "language": "pl",
                    "description": text,
                },
                ensure_ascii=False,
            )
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _front_matter(doc_id: str, version: int, title: str, valid_from: date, valid_to: date | None) -> str:
    return (
        f"---\ndoc_id: {doc_id}\nversion: {version}\ntitle: {title}\nlanguage: pl\n"
        f"valid_from: {valid_from.isoformat()}\nvalid_to: {valid_to.isoformat() if valid_to else 'null'}\n---\n\n"
    )


def policies(world: World) -> dict[str, str]:
    """Regulaminy NovaCart. Polityka zwrotów i dostawy zmieniają się w trakcie okresu (wersja 2)."""
    start = world.cfg.start_date - timedelta(days=365)
    change = world.cfg.start_date + timedelta(days=world.cfg.days // 2)
    docs: dict[str, str] = {}

    docs["regulamin-v1.md"] = (
        _front_matter("regulamin", 1, "Regulamin marketplace'u NovaCart", start, None) + REGULAMIN
    )
    docs["zwroty-v1.md"] = (
        _front_matter("zwroty", 1, "Polityka zwrotów", start, change - timedelta(days=1)) + ZWROTY_V1
    )
    docs["zwroty-v2.md"] = _front_matter("zwroty", 2, "Polityka zwrotów", change, None) + ZWROTY_V2.format(
        change=change.strftime("%d.%m.%Y")
    )
    docs["dostawa-v1.md"] = _front_matter("dostawa", 1, "Dostawa i przewoźnicy", start, None) + DOSTAWA
    docs["platnosci-v1.md"] = _front_matter("platnosci", 1, "Metody płatności", start, None) + PLATNOSCI
    docs["prywatnosc-v1.md"] = (
        _front_matter("prywatnosc", 1, "Polityka prywatności", start, None) + PRYWATNOSC
    )
    docs["faq-v1.md"] = _front_matter("faq", 1, "Najczęściej zadawane pytania", start, None) + FAQ
    return docs


REGULAMIN = """# Regulamin marketplace'u NovaCart

## 1. Postanowienia ogólne

NovaCart jest platformą handlową (marketplace), na której niezależni sprzedawcy oferują produkty
klientom w Polsce, Niemczech, Czechach, na Słowacji, Litwie i w Holandii. Umowa sprzedaży zawierana
jest pomiędzy klientem a sprzedawcą; NovaCart pośredniczy w zawarciu umowy, obsłudze płatności
i komunikacji.

## 2. Konto klienta

Do złożenia zamówienia wymagane jest konto. Klient może w każdej chwili zmienić dane konta,
wycofać zgodę marketingową lub złożyć wniosek o usunięcie danych osobowych (patrz: Polityka prywatności).

## 3. Zamówienia

1. Zamówienie może obejmować produkty wielu sprzedawców. Każda pozycja jest realizowana przez
   sprzedawcę, który ją oferuje.
2. Złożenie zamówienia oznacza obowiązek zapłaty. Zamówienie nieopłacone w ciągu 1 godziny
   (lub 72 godzin w przypadku przelewu tradycyjnego) jest automatycznie anulowane.
3. Klient może anulować opłacone zamówienie do momentu jego nadania. Środki zwracane są tą samą
   metodą płatności w ciągu 3 dni roboczych.

## 4. Ceny

Ceny podawane są w walucie kraju dostawy (PLN, EUR lub CZK) i zawierają podatek VAT. Ceny mogą się
zmieniać; wiążąca jest cena z chwili złożenia zamówienia. Kody promocyjne obniżają cenę wybranych pozycji.

## 5. Reklamacje

Reklamacje dotyczące produktu rozpatruje sprzedawca w terminie 14 dni. Reklamacje dotyczące działania
platformy rozpatruje NovaCart. Klient może zgłosić reklamację przez formularz w aplikacji lub e-mailem.
"""

ZWROTY_V1 = """# Polityka zwrotów

## Termin

Klient może odstąpić od umowy bez podania przyczyny w terminie **14 dni** od dnia doręczenia przesyłki.

## Jak zwrócić produkt

1. Zgłoś zwrot w aplikacji NovaCart (zakładka „Moje zamówienia”).
2. Wydrukuj etykietę zwrotną i nadaj paczkę u przewoźnika wskazanego w zgłoszeniu.
3. Po otrzymaniu zwrotu przez sprzedawcę środki wracają w ciągu 5 dni roboczych.

## Koszty

Koszt odesłania produktu ponosi klient. Wyjątek: produkty wadliwe lub niezgodne z opisem.

## Wyłączenia

Zwrotowi nie podlegają produkty higieniczne po otwarciu opakowania, otwarte nośniki z grami i muzyką
oraz żywność.
"""

ZWROTY_V2 = """# Polityka zwrotów

> Wersja obowiązuje od {change}. Najważniejsza zmiana: wydłużenie terminu zwrotu do 30 dni
> i darmowe zwroty dla kategorii Moda.

## Termin

Klient może odstąpić od umowy bez podania przyczyny w terminie **30 dni** od dnia doręczenia przesyłki.
Dla zamówień doręczonych przed {change} obowiązuje dotychczasowy termin 14 dni.

## Jak zwrócić produkt

1. Zgłoś zwrot w aplikacji NovaCart (zakładka „Moje zamówienia”).
2. Wybierz punkt nadania lub zamów kuriera — etykieta zwrotna generuje się automatycznie.
3. Po otrzymaniu zwrotu przez sprzedawcę środki wracają w ciągu 5 dni roboczych.

## Koszty

Zwroty produktów z kategorii **Moda** (odzież, obuwie, torby, biżuteria) są **bezpłatne**.
W pozostałych kategoriach koszt odesłania ponosi klient, chyba że produkt jest wadliwy.

## Wyłączenia

Zwrotowi nie podlegają produkty higieniczne po otwarciu opakowania, otwarte nośniki z grami i muzyką
oraz żywność.
"""

DOSTAWA = """# Dostawa i przewoźnicy

## Koszt dostawy

| Waluta | Darmowa dostawa od | Opłata za dostawę poniżej progu |
|---|---|---|
| PLN | 399,00 zł | 14,99 zł |
| EUR | 99,00 € | 4,99 € |
| CZK | 2 499 Kč | 129 Kč |

Próg liczony jest od wartości zamówienia po rabatach.

## Przewoźnicy

- **SpeedPost** — dostawy krajowe w Polsce oraz wybrane trasy do Czech, Słowacji i na Litwę.
- **EuroParcel** — dostawy we wszystkich krajach działania NovaCart.
- **QuickShip** — Niemcy, Holandia, Czechy, Słowacja i Litwa.

## Czas dostawy

Sprzedawca przygotowuje przesyłkę zwykle w ciągu 24 godzin od opłacenia zamówienia (w przypadku
płatności za pobraniem — od złożenia zamówienia). Dostawa krajowa trwa zwykle 1–2 dni robocze,
dostawa międzynarodowa 2–5 dni roboczych.

## Nieudane doręczenie

Jeśli kurier nie zastanie odbiorcy, ponowi próbę doręczenia następnego dnia roboczego.
"""

PLATNOSCI = """# Metody płatności

| Metoda | Dostępność | Uwagi |
|---|---|---|
| Karta płatnicza (Visa, Mastercard, American Express) | wszystkie kraje | obciążenie natychmiastowe |
| BLIK | Polska | potwierdzenie w aplikacji banku |
| PayPal | wszystkie kraje | |
| Przelew tradycyjny | wszystkie kraje | zaksięgowanie do 1 dnia roboczego; zamówienie czeka 72 h |
| iDEAL | Holandia | |
| Płatność przy odbiorze (za pobraniem) | wszystkie kraje | płatność kurierowi przy doręczeniu |

## Odrzucone płatności

Jeśli płatność zostanie odrzucona (np. brak środków, wygaśnięcie karty), klient może ponowić próbę
w ciągu godziny. Po tym czasie zamówienie jest anulowane.

## Zwrot środków

Zwrot środków (anulowanie, zwrot produktu) realizowany jest tą samą metodą, którą dokonano płatności.
"""

PRYWATNOSC = """# Polityka prywatności

## Administrator danych

Administratorem danych osobowych klientów jest NovaCart (spółka fikcyjna, na potrzeby kursu).

## Jakie dane przetwarzamy

- dane konta: imię, nazwisko, adres e-mail, numer telefonu, data urodzenia,
- adres dostawy,
- historia zamówień i płatności (bez pełnych numerów kart — przechowujemy tylko 4 ostatnie cyfry),
- dane o korzystaniu z aplikacji: identyfikator urządzenia, adres IP, przeglądane produkty.

## Prawo do usunięcia danych

Klient może w każdej chwili złożyć wniosek o usunięcie danych (art. 17 RODO) — przez formularz,
e-mail lub dział obsługi klienta. Wniosek realizujemy w ciągu maksymalnie 30 dni. Dane konta są
anonimizowane; dane transakcyjne wymagane przepisami podatkowymi przechowujemy w formie
uniemożliwiającej identyfikację klienta.

## Zgody marketingowe

Zgodę marketingową można wycofać w ustawieniach konta. Wycofanie zgody nie wpływa na realizację zamówień.
"""

FAQ = """# Najczęściej zadawane pytania

## Kiedy otrzymam przesyłkę?

Zwykle w ciągu 1–2 dni roboczych w kraju i 2–5 dni roboczych przy wysyłce z innego kraju.
Numer przesyłki znajdziesz w szczegółach zamówienia po jego nadaniu.

## Czy mogę zmienić adres dostawy po złożeniu zamówienia?

Tylko do momentu nadania przesyłki — skontaktuj się z obsługą klienta.

## Jak użyć kodu promocyjnego?

Wpisz kod w koszyku przed przejściem do płatności. Kody nie łączą się ze sobą.

## Dlaczego moje zamówienie zostało anulowane?

Najczęstsze powody: brak płatności w wymaganym czasie (1 godzina, a dla przelewu 72 godziny)
albo anulowanie na Twoją prośbę.

## Jak usunąć konto?

Złóż wniosek o usunięcie danych w ustawieniach konta. Szczegóły: Polityka prywatności.
"""
