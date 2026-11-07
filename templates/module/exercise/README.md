<!--
AUTOR: Treść zadania końcowego. Zadanie ma być realistyczne, mierzalne i wykonalne
w czasie podanym w konspekcie. Wyniki muszą być porównywalne między uczestnikami,
dlatego dane pochodzą z generatora z ustalonymi parametrami (w tym --seed).
-->

# 🧪 Zadanie końcowe — {{Tytuł zadania}}

| | |
|---|---|
| **Moduł** | [{{NN}} — {{Tytuł modułu}}](../README.md) |
| **Szacowany czas** | {{N}} h |
| **Szacowany koszt** | {{np. ~1,50 USD (BigQuery on-demand ~200 GB skanowania)}} |
| **Sprawdzane cele modułu** | {{1, 3, 4}} |

## Kontekst biznesowy

<!-- AUTOR: Sytuacja w NovaCart, rola uczestnika, kto jest „klientem” rozwiązania i czego oczekuje. -->

{{„Jesteś data engineerem w zespole platformy danych NovaCart. Dział finansów zgłasza, że…”}}

## Cel

{{Jedno–dwa zdania: co dokładnie ma powstać.}}

## Dane wejściowe

```bash
cd datasets
uv run novacart generate --scale {{m}} --seed 42 --components {{…}} -o ../data/exercise-{{NN}}
```

{{Opis istotnych tabel/plików i ewentualnych cech danych, na które warto zwrócić uwagę (bez zdradzania rozwiązania).}}

## Wymagania

### Funkcjonalne

1. {{…}}
2. {{…}}

### Niefunkcjonalne

- {{Wydajność: np. zapytanie X przetwarza < 5 GB}}
- {{Koszt: np. miesięczny koszt rozwiązania < Y przy skali L}}
- {{Niezawodność / idempotencja: np. ponowne uruchomienie daje ten sam wynik}}
- {{Bezpieczeństwo: np. brak kluczy SA, least privilege}}
- Cała infrastruktura w Terraform; wszystko da się usunąć jednym poleceniem

## Kryteria akceptacji

<!-- AUTOR: Mierzalne, sprawdzalne punkty. Uczestnik odhacza je samodzielnie. -->

- [ ] {{np. Tabela `marts.daily_sales` zawiera dokładnie {{N}} wierszy dla skali M, seed 42}}
- [ ] {{np. Zapytanie z pliku `queries/q1.sql` przetwarza mniej niż {{X}} GB (dry run)}}
- [ ] {{np. Ponowne uruchomienie pipeline'u dla dnia 2025-11-28 nie zmienia wyników}}
- [ ] {{np. Raport zawiera porównanie co najmniej dwóch wariantów z pomiarami}}
- [ ] Skrypt sprzątający usuwa wszystkie utworzone zasoby

## Rezultaty do oddania

```text
exercise/
├── README.md            # Twój raport: decyzje, pomiary, wnioski (szablon poniżej)
├── {{src/}}             # kod
├── {{terraform/}}       # infrastruktura
└── {{cleanup.sh}}       # sprzątanie
```

**Szablon raportu** (w Twoim `README.md`):

1. Podsumowanie (3–5 zdań)
2. Architektura / podejście (diagram)
3. Kluczowe decyzje i odrzucone alternatywy
4. Pomiary (tabela przed/po, koszty)
5. Ograniczenia i co zrobił(a)byś dalej

## Podpowiedzi

<!-- AUTOR: Od najogólniejszej do najbardziej konkretnej. Ostatnia może prawie zdradzać rozwiązanie. -->

<details>
<summary>Podpowiedź 1 — kierunek</summary>

{{Ogólna wskazówka: na co zwrócić uwagę, który mechanizm z lekcji jest kluczowy.}}

</details>

<details>
<summary>Podpowiedź 2 — narzędzie</summary>

{{Konkretne narzędzie / funkcja / widok INFORMATION_SCHEMA, który pomoże.}}

</details>

<details>
<summary>Podpowiedź 3 — prawie rozwiązanie</summary>

{{Szkic podejścia.}}

</details>

## Ocena

| Kryterium | Waga | Co oznacza „bardzo dobrze” |
|---|---|---|
| Poprawność | 30% | Wszystkie kryteria akceptacji spełnione; wyniki zgodne z oczekiwanymi |
| Jakość decyzji | 25% | Decyzje uzasadnione pomiarami; rozważone alternatywy i kompromisy |
| Wydajność i koszt | 20% | Mierzalna optymalizacja; koszt oszacowany i uzasadniony |
| Jakość kodu i IaC | 15% | Czytelny, przetestowany kod; infrastruktura w Terraform |
| Raport | 10% | Zwięzły, z diagramem, pomiarami i wnioskami |

## Rozszerzenia (dla ambitnych)

- {{Wariant na innej platformie: np. „Zaimplementuj to samo w Snowflake i porównaj koszt”}}
- {{Wariant w większej skali: np. „Powtórz pomiary dla skali L i wyjaśnij różnice”}}
- {{Wariant produkcyjny: np. „Dodaj monitoring i alert na …”}}

## Sprzątanie

```bash
{{./cleanup.sh   lub   terraform destroy}}
```

> [!CAUTION]
> Nie zostawiaj działających zasobów po zakończeniu zadania. Sprawdź w Billing → Reports, czy koszty projektu przestały rosnąć.

---

<sub>Rozwiązanie wzorcowe: [solution/](solution/README.md). Zajrzyj tam dopiero po samodzielnej próbie.</sub>
