# Szablony i przewodnik autora

Ten katalog zawiera szablon modułu kursu oraz zasady, dzięki którym wszystkie moduły mają tę samą strukturę, ton i poziom szczegółowości.

```text
templates/
├── README.md                      # ten plik: przewodnik autora
└── module/                        # szablon do skopiowania
    ├── README.md                  # strona główna modułu
    ├── 01-nazwa-lekcji.md         # szablon lekcji (kopiuj dla każdej lekcji)
    ├── examples/README.md         # indeks przykładów kodu
    └── exercise/
        ├── README.md              # treść zadania końcowego
        ├── starter/README.md      # kod startowy
        └── solution/README.md     # omówienie rozwiązania
```

---

## Jak utworzyć nowy moduł

```bash
NN=14; SLUG=bigquery-architektura
cp -R templates/module "modules/${NN}-${SLUG}"
mv "modules/${NN}-${SLUG}/01-nazwa-lekcji.md" "modules/${NN}-${SLUG}/01-<pierwsza-lekcja>.md"
```

1. Uzupełnij `README.md` modułu na podstawie konspektu w głównym [README](../README.md).
2. Dla każdej lekcji skopiuj `01-nazwa-lekcji.md` i nadaj kolejne numery (`02-…`, `03-…`).
3. Napisz przykłady w `examples/`, a zadanie w `exercise/`.
4. Usuń wszystkie komentarze `<!-- AUTOR: … -->` i znaczniki `{{…}}`.
5. Przejdź checklistę [Definition of Done](#definition-of-done).
6. Zmień status części w głównym README.

**Nazewnictwo:** katalogi i pliki `kebab-case`, bez polskich znaków (`02-partycjonowanie-i-clustering.md`). Numer lekcji to dwie cyfry.

---

## Dla kogo piszemy

Czytelnik to **praktykujący inżynier**. Zna SQL i Pythona, budował pipeline'y i chce zrozumieć, *dlaczego* narzędzia działają tak, jak działają. Nie jest akademikiem i nie ma czasu na ogólniki.

Każdy temat prowadzimy po **drabinie głębokości**:

| Szczebel | Pytanie | Forma |
|---|---|---|
| 1. Problem | Po co to istnieje? Co bolało wcześniej? | Scenariusz NovaCart, 2–4 zdania |
| 2. Intuicja | Jak o tym myśleć? | Analogia, prosty diagram |
| 3. Model | Jakie są pojęcia i reguły? | Definicje, diagram architektury |
| 4. Pod maską | Jak to jest zbudowane? | Struktury danych, algorytmy, przepływ krok po kroku |
| 5. Konsekwencje | Co z tego wynika w praktyce? | Reguły projektowe, antywzorce, koszty |
| 6. Praktyka | Jak to zrobić dobrze? | Działający kod + pomiar efektu |

Szczebel 5 jest obowiązkowy po każdym szczeblu 4. Wiedza „pod maską” bez wniosków praktycznych to ciekawostka, a nie materiał kursu.

---

## Język i ton

- **Po polsku, ale bez spolszczania na siłę.** Terminy, które w branży funkcjonują po angielsku, zostawiamy po angielsku: *shuffle*, *slot*, *watermark*, *partition pruning*, *data skew*, *exactly-once*, *backfill*. Przy **pierwszym** użyciu w lekcji piszemy je kursywą i krótko wyjaśniamy, np. „*shuffle* (przetasowanie danych między maszynami)”.
- Tam, gdzie polski termin jest naturalny, używamy go: partycjonowanie, replikacja, spójność, kolumnowy, opóźnienie.
- Nazwy usług, poleceń, API i parametrów zapisujemy dokładnie tak, jak w dokumentacji: `BigQuery`, `Storage Write API`, `maximum_bytes_billed`.
- **Zwracamy się do czytelnika na „ty”**: „zauważ”, „sprawdź”, „uruchom”.
- **Konkret zamiast przymiotników.** Zamiast „BigQuery jest bardzo szybkie” piszemy „zapytanie przeskanowało 1,2 TB w 9 s, używając średnio 2 000 slotów”.
- **Bez marketingu i bez kibicowania dostawcom.** Każda platforma ma mocne i słabe strony i opisujemy jedne i drugie.
- Liczby zapisujemy po polsku w tekście (`1,5 GB`, `10 000`), a w kodzie i tabelach technicznych tak, jak wymaga składnia.

### Słowniczek decyzji językowych

| Używamy | Unikamy |
|---|---|
| partycja, partycjonowanie | „partition” w zdaniu po polsku |
| *clustering* (BigQuery), klastrowanie (ogólnie) | „grupowanie” |
| *shuffle* | „tasowanie”, „mieszanie” |
| *slot* | „gniazdo” |
| zapytanie | „kwerenda” |
| potok danych / *pipeline* | „rurociąg” |
| hurtownia danych | „magazyn danych” (myli się z *storage*) |
| ziarno losowości / *seed* | — |

Pełny słownik pojęć znajduje się w `appendices/` (Dodatek A).

---

## Bloki wyróżnione (callouts)

Używamy natywnych alertów GitHub. Każdy typ ma **stałe znaczenie**:

```markdown
> [!TIP]
> **Intuicja.** Analogia lub uproszczony model myślowy.

> [!NOTE]
> **Pod maską.** Dygresja techniczna dla dociekliwych; można ją pominąć bez utraty wątku.

> [!IMPORTANT]
> **Kluczowy wniosek.** Jedna rzecz, którą trzeba zapamiętać z danej sekcji.

> [!WARNING]
> **Pułapka.** Typowy błąd, jego objaw i sposób uniknięcia.

> [!CAUTION]
> **Koszt!** Operacja, która może wygenerować istotny rachunek lub jest nieodwracalna.
```

Nie więcej niż jeden blok `IMPORTANT` na sekcję. Jeśli wszystko jest ważne, nic nie jest.

---

## Diagramy

- **Mermaid** dla architektur, przepływów i sekwencji (renderuje się na GitHubie i w VS Code).
- **ASCII** dla struktur danych i układu bajtów (np. budowa pliku Parquet, drzewo LSM), bo Mermaid się do tego nie nadaje.
- Każdy diagram ma podpis, który mówi, **co** czytelnik ma na nim zauważyć.
- Diagram uzupełnia tekst, a nie go zastępuje. Opisz go zdaniem przed lub po.

---

## Kod

| Zasada | Szczegóły |
|---|---|
| Działa | Każdy fragment da się uruchomić. Fragmenty w tekście pochodzą z plików w `examples/` i mają podany plik źródłowy. |
| Jest przetestowany | Przykłady Pythona mają testy lub są uruchamiane w CI; zapytania SQL zostały wykonane na danych NovaCart. |
| Ma wynik | Pod kodem pokazujemy oczekiwany wynik albo jego fragment (i na jakiej skali danych). |
| Jest minimalny | Pokazuje jedną ideę. Logowanie, obsługa błędów i konfiguracja tylko wtedy, gdy są tematem. |
| Jest bezpieczny | Bez kluczy i haseł w kodzie. Zasoby chmurowe mają etykiety `course=ade` i `module=NN`. |
| Ma wersje | Wersje bibliotek przypięte w `pyproject.toml` / `requirements.txt`; wersje providerów Terraform w `required_providers`. |
| Sprząta po sobie | Każdy przykład tworzący zasoby ma polecenie lub skrypt sprzątający. |

Konwencje języków: SQL w dialekcie GoogleSQL (inne dialekty wyraźnie oznaczone), słowa kluczowe WIELKIMI literami. Python 3.12+ z typowaniem, formatowany `ruff`. Terraform: zmienne opisane, etykiety na każdym zasobie.

Blok kodu zaczynamy komentarzem ze ścieżką pliku:

````markdown
```python
# examples/02_partition_pruning.py
from google.cloud import bigquery
...
```
````

---

## Fakty o usługach chmurowych

Usługi zmieniają się szybciej niż książki. Dlatego:

1. **Każde twierdzenie o limicie, cenie, wersji lub zachowaniu usługi** ma link do oficjalnej dokumentacji w sekcji „Źródła” lekcji.
2. Każda lekcja ma w nagłówku **datę ostatniej weryfikacji**.
3. Ceny podajemy jako przykład rzędu wielkości („około 6 USD za TiB w modelu on-demand, stan na …”), nigdy jako stałą prawdę. W zadaniach liczymy koszty według aktualnego cennika.
4. Funkcje w *preview* oznaczamy wprost: **(Preview)**.
5. Gdy opisujemy wewnętrzną architekturę (np. Dremel, Colossus), rozróżniamy fakty z publikacji i dokumentacji od uzasadnionych wniosków („z papera X wynika…”, „można przypuszczać…”).

---

## Porównania platform

Sekcja porównawcza w lekcji odpowiada na pytanie: **jak ten sam problem rozwiązują inne platformy i dlaczego inaczej?** Nie jest listą odpowiedników nazw usług.

Stały zestaw kolumn (pomiń te, które nie mają sensu w danym temacie):

| Aspekt | GCP | AWS | Azure | Snowflake | Databricks | On-prem / OSS |
|---|---|---|---|---|---|---|

Pod tabelą zawsze piszemy 2–5 zdań wniosków: gdzie różnice są fundamentalne (architektura), a gdzie kosmetyczne (nazewnictwo).

---

## Zadanie końcowe

Dobre zadanie:

- ma **kontekst biznesowy** NovaCart i jasno określony rezultat,
- korzysta z **generatora danych** z podanymi parametrami (`datasets/`), żeby wyniki były porównywalne,
- ma **mierzalne kryteria akceptacji** (checklista), a nie „zrób dobrze”,
- wymaga **pomiaru** (czas, bajty, koszt), a nie tylko działającego kodu,
- ma **stopniowane podpowiedzi** ukryte w `<details>`,
- podaje **szacowany koszt** i polecenie sprzątające,
- ma **rozszerzenia** dla ambitnych,
- da się je wykonać w czasie podanym w konspekcie.

Rozwiązanie (`exercise/solution/`) omawia **decyzje i alternatywy**, a nie tylko pokazuje kod.

---

## Definition of Done

Moduł jest gotowy, gdy:

- [ ] `README.md` modułu jest kompletny: cele, wymagania, mapa lekcji, podsumowanie, pytania kontrolne
- [ ] każda lekcja ma wszystkie sekcje szablonu albo uzasadnienie, dlaczego którejś brakuje
- [ ] każda lekcja ma sekcję „Pod maską” i po niej wnioski praktyczne
- [ ] każda lekcja ma porównanie platform z wnioskami
- [ ] każdy fragment kodu pochodzi z `examples/` i został uruchomiony
- [ ] zadanie końcowe ma kryteria akceptacji, koszt, sprzątanie i rozwiązanie
- [ ] wszystkie fakty o usługach mają źródła, a lekcje mają datę weryfikacji
- [ ] terminy angielskie są wyjaśnione przy pierwszym użyciu
- [ ] diagramy się renderują (podgląd na GitHubie lub w VS Code)
- [ ] brak komentarzy `<!-- AUTOR: … -->` i znaczników `{{…}}`
- [ ] linki względne działają
- [ ] status modułu w głównym README został zaktualizowany
