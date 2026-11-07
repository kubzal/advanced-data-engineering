# 🧪 Zadanie końcowe — Trzy epoki, jedna NovaCart: architektura i ADR

| | |
|---|---|
| **Moduł** | [01 — Ewolucja architektur danych](../README.md) |
| **Szacowany czas** | 4–6 h |
| **Szacowany koszt** | 0 USD (praca koncepcyjna; generator w skali S uruchamiasz lokalnie) |
| **Sprawdzane cele modułu** | 2, 3, 4, 5, 6, 7 (porównanie epok, architektury równoległe, separacja storage i compute, lakehouse, ocena trendów, ADR) |

## Kontekst biznesowy

Jesteś nowym data architectem w NovaCart. Zarząd przygotowuje plan na trzy lata: firma chce wejść na kolejne rynki i spodziewa się **dziesięciokrotnego** wzrostu ruchu (ze skali L do skali XL generatora). Obecna platforma danych to zlepek: kopia bazy PostgreSQL do raportów, skrypty ładujące pliki przewoźników i clickstream w Cloud Storage, z którego nikt poza data science nie korzysta.

CTO prosi Cię o dokument decyzyjny. Część zarządu pamięta „wielki projekt Hadoop” z poprzedniej firmy i jest sceptyczna wobec rewolucji, inni chcą „lakehouse'u jak Netflix”. Żeby rozmowa była rzeczowa, CTO chce zobaczyć **tę samą firmę w trzech architekturach**: tak, jak zbudowano by ją w 2010 r. on-premise, jako hurtownię chmurową i jako lakehouse. Ma to być opisane tym samym językiem: przepływy, punkty awarii, skalowanie, koszty i właściciele. Na końcu chce rekomendacji w formie **ADR** (*Architecture Decision Record*), którą da się przedstawić zarządowi i za rok zweryfikować.

## Cel

Przygotuj opis trzech wariantów architektury danych NovaCart: (a) **on-premise 2010** (Hadoop + hurtownia MPP), (b) **cloud data warehouse**, (c) **lakehouse**. Następnie napisz ADR z rekomendacją wariantu na dziś.

## Dane wejściowe

Zadanie jest koncepcyjne, ale liczby muszą być prawdziwe. Wspólne założenia wolumenowe są w [starter/zalozenia-wolumenowe.md](starter/zalozenia-wolumenowe.md). Pochodzą z generatora NovaCart i możesz je zweryfikować:

```bash
cd datasets
uv run novacart info                                               # wolumeny dla skal L i XL
uv run novacart generate --scale s --seed 42 --components all -o ../data/s
```

Na danych w skali S możesz sam zmierzyć stosunek rozmiaru JSON do Parquet, liczbę zmian CDC na zamówienie i liczbę plików od przewoźników dziennie. Wszystkie źródła NovaCart opisuje [dokumentacja generatora](../../../datasets/README.md):

| Źródło | Charakter | Na co zwrócić uwagę przy projektowaniu |
|---|---|---|
| Baza transakcyjna (PostgreSQL) | zamówienia, klienci, produkty, sprzedawcy; ciągłe zmiany | CDC (ok. 3,8 zmiany na zamówienie), RODO, obciążenie produkcji |
| Clickstream web/mobile | największy wolumen, duplikaty, zdarzenia spóźnione do 72 h | szczyt Black Friday, świeżość dla personalizacji |
| Pliki przewoźników | 3 formaty, Windows-1250, zmiana schematu bez zapowiedzi | odporność ingestu, schema-on-read vs schema-on-write |
| API płatności | stronicowanie, limity zapytań, PII | inkrementalne pobieranie, bezpieczeństwo |
| Dokumenty (regulaminy, opisy) | dane nieustrukturyzowane, wersje | przyszły asystent AI (moduł 42) |

**Konsumenci**, których musi obsłużyć każdy wariant:

1. raport przychodu dla finansów (dzienny, musi zgadzać się z księgowością),
2. dashboardy operacyjne (dostawy, zwroty; odświeżanie co 15 min),
3. model rekomendacji produktów (trening dzienny na historii clickstreamu i zamówień),
4. wykrywanie anomalii w clickstreamie (np. spadek zdarzeń z Androida) w ciągu 15 minut.

## Wymagania

### Funkcjonalne

1. Dla każdego z trzech wariantów przygotuj (szablon: [starter/warianty-template.md](starter/warianty-template.md)):
   - diagram architektury w Mermaid: wszystkie 4 źródła → przetwarzanie → storage → 4 konsumentów, z nazwanymi technologiami właściwymi dla epoki,
   - opis przepływu danych dla **jednego zamówienia** od złożenia w sklepie do pojawienia się w raporcie przychodu, z opóźnieniem na każdym etapie,
   - co najmniej **3 punkty awarii** z wpływem na konsumentów i sposobem mitygacji,
   - opis **skalowania**: co trzeba zrobić, ile to trwa i kto to robi przy (a) Black Friday (×2,8 wolumenu dziennego) i (b) wzroście do skali XL,
   - **model kosztowy** na 3 lata (TCO): storage, compute, licencje, ludzie, z jawnymi założeniami i ceną jednostkową dla każdej pozycji, w USD jako rząd wielkości,
   - **mapę właścicieli** komponentów (role z lekcji 01.08),
   - opis obsługi dwóch scenariuszy: **wniosek RODO o usunięcie klienta** i **sprzedawca przysyła ceny w groszach** (anomalia z lekcji 01.06).
2. Przygotuj tabelę porównawczą trzech wariantów z co najmniej 8 kryteriami (np. świeżość, koszt stały vs zmienny, elastyczność, kompetencje zespołu, ryzyko uzależnienia od dostawcy, obsługa ML, governance, czas wdrożenia).
3. Napisz ADR z rekomendacją (szablon: [starter/adr-template.md](starter/adr-template.md)).

### Niefunkcjonalne

- **Spójność liczb:** wszystkie wolumeny pochodzą z [arkusza założeń](starter/zalozenia-wolumenowe.md) albo są jawnie zmienione z uzasadnieniem.
- **Weryfikowalność:** każda cena jednostkowa ma źródło (cennik z datą) albo jest oznaczona jako założenie.
- **Uczciwość porównania:** każdy wariant ma wypisane mocne strony, nie tylko słabe. Wariant on-prem 2010 oceniaj według realiów 2010 r., a nie dzisiejszych.
- **Zwięzłość:** dokument dla zarządu. Każdy wariant mieści się na 2–3 ekranach, a ADR na jednym.

## Kryteria akceptacji

- [ ] Są trzy warianty, a każdy ma diagram Mermaid, który renderuje się na GitHubie lub w VS Code
- [ ] Każdy diagram obejmuje 4 źródła i 4 konsumentów z sekcji „Dane wejściowe”
- [ ] Każdy wariant opisuje przepływ jednego zamówienia z opóźnieniem na każdym etapie i opóźnieniem końcowym
- [ ] Każdy wariant ma co najmniej 3 punkty awarii z wpływem i mitygacją
- [ ] Każdy wariant ma opis skalowania na Black Friday (×2,8) i do skali XL, z czasem potrzebnym na zwiększenie mocy
- [ ] Każdy wariant ma TCO na 3 lata rozbite na co najmniej 4 kategorie, z jawnymi cenami jednostkowymi i założeniami
- [ ] Każdy wariant ma mapę właścicieli komponentów (bez komponentów „bez właściciela”)
- [ ] Każdy wariant opisuje obsługę wniosku RODO i anomalii cen w groszach
- [ ] Tabela porównawcza ma co najmniej 8 kryteriów
- [ ] ADR ma sekcje: kontekst, czynniki decyzji, rozważone opcje, decyzja, co najmniej 2 odrzucone alternatywy z uzasadnieniem, konsekwencje pozytywne i negatywne, warunki rewizji decyzji
- [ ] Liczby wolumenów są zgodne z arkuszem założeń (albo zmiany są uzasadnione)

## Rezultaty do oddania

```text
exercise/
├── README.md                 # Twój raport (szablon poniżej)
├── warianty.md               # trzy warianty (na podstawie starter/warianty-template.md)
├── porownanie.md             # tabela porównawcza (może być częścią README)
└── adr-001-platforma-danych.md
```

**Szablon raportu** (w Twoim `README.md`):

1. Podsumowanie (3–5 zdań): rekomendacja i najważniejszy powód
2. Architektura: link do `warianty.md` i diagram rekomendowanego wariantu
3. Kluczowe decyzje i odrzucone alternatywy: link do ADR
4. Pomiary i liczby: tabela wolumenów, tabela TCO trzech wariantów
5. Ograniczenia i co zrobił(a)byś dalej: czego nie wiesz i jak byś to sprawdził(a)

## Podpowiedzi

<details>
<summary>Podpowiedź 1 — kierunek</summary>

Zacznij od arkusza założeń i policz **szczyt**, a nie średnią: ile zdarzeń na sekundę w najgorętszej godzinie Black Friday przy skali XL? Potem dla każdego wariantu zapytaj: który komponent nasyci się pierwszy? To będzie Twój główny punkt awarii i główna pozycja w opisie skalowania. Wróć do lekcji 01.07: w wariancie on-prem moc kupujesz z wyprzedzeniem na szczyt, a w chmurze płacisz za użycie.

</details>

<details>
<summary>Podpowiedź 2 — narzędzia i źródła</summary>

- Ceny chmurowe: cenniki BigQuery, Cloud Storage, Dataflow, Dataproc i Pub/Sub. Zapisz datę odczytu. Do szybkich szacunków możesz użyć Google Cloud Pricing Calculator.
- Wariant 2010: rzędy wielkości dla serwerów, macierzy i appliance'ów MPP z tamtego okresu oznacz jako założenia. Nie musisz znać dokładnych cen. Ważniejsze jest, że koszt jest **stały** i ponoszony **z góry**.
- Ludzie: przyjmij koszt pełnego etatu (FTE) i policz, ilu osób wymaga utrzymanie każdego wariantu. W wariancie on-prem to często największa pozycja.
- Format ADR: Michael Nygard, „Documenting Architecture Decisions” (2011), albo MADR (*Markdown Architectural Decision Records*).

</details>

<details>
<summary>Podpowiedź 3 — prawie rozwiązanie</summary>

Szkielet, który działa:

- (a) **On-prem 2010:** Sqoop/Flume → HDFS (surowe) → Hive/MapReduce (przetwarzanie nocne) → hurtownia MPP (np. Netezza/Greenplum) → raporty BI; ML na Hadoopie (Mahout lub Python na eksportach); brak realnego streamingu (anomalie wykrywane następnego dnia, chyba że dodasz Storm, czyli Lambdę). Klaster i appliance kupione na szczyt.
- (b) **Cloud DW:** Datastream (CDC) + Pub/Sub/Dataflow (clickstream) + ładowanie plików do BigQuery → transformacje w Dataform/dbt → BigQuery jako jedyny storage analityczny → Looker; ML przez BigQuery ML lub eksport do Vertex AI; anomalie przez zapytania ciągłe lub Dataflow.
- (c) **Lakehouse:** te same źródła → Iceberg na GCS (BigLake metastore) → Spark (Dataproc Serverless) i BigQuery na tych samych tabelach → BI i ML bezpośrednio z tabel Iceberg.

W ADR uczciwie porównaj (b) i (c). Na GCP i przy zespole znającym SQL różnica sprowadza się do pytania, czy potrzebujesz wielu silników zapisujących te same dane.

</details>

## Ocena

| Kryterium | Waga | Co oznacza „bardzo dobrze” |
|---|---|---|
| Poprawność | 30% | Wszystkie kryteria akceptacji spełnione; technologie pasują do epok; liczby spójne z założeniami |
| Jakość decyzji | 25% | ADR uzasadniony liczbami i kompromisami; odrzucone alternatywy potraktowane poważnie; warunki rewizji mierzalne |
| Wydajność i koszt | 20% | TCO z jawnymi założeniami; rozróżnienie kosztów stałych i zmiennych; uwzględniony szczyt i wzrost ×10 |
| Jakość opisu architektury | 15% | Czytelne diagramy, konkretne punkty awarii i mitygacje, właściciele komponentów |
| Raport | 10% | Zwięzły, zrozumiały dla zarządu, z jasną rekomendacją w pierwszym akapicie |

## Rozszerzenia (dla ambitnych)

- **Czwarty wariant: Snowflake lub Databricks na GCP.** Jak zmienia się TCO, ryzyko uzależnienia od dostawcy i model kompetencji zespołu?
- **Data mesh za 3 lata.** Przy 10× większej skali NovaCart będzie miała 6–8 domen. Jak rekomendowany wariant zmieni się w organizację domenową? Których elementów platformy brakuje?
- **Analiza wrażliwości.** Które założenie (np. liczba zapytań dashboardów, koszt FTE, wzrost) najbardziej zmienia rekomendację? Przy jakiej wartości decyzja się odwraca?
- **Weryfikacja na danych.** Zmierz na danych w skali S, ile bajtów skanuje typowe zapytanie raportu przychodu z partycjonowaniem po dniu i bez niego (DuckDB), i przeskaluj wynik na skalę XL.

## Sprzątanie

Zadanie nie tworzy zasobów w chmurze. Jeśli generowałeś dane lokalnie, możesz je usunąć:

```bash
rm -rf data/s
```

---

<sub>Rozwiązanie wzorcowe: [solution/](solution/README.md). Zajrzyj tam dopiero po samodzielnej próbie.</sub>
