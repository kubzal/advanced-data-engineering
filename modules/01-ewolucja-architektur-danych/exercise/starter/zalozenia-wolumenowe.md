# Arkusz założeń wolumenowych NovaCart

Wspólne liczby dla wszystkich wariantów. Dzięki nim rozwiązania różnych osób są porównywalne. Jeśli zmieniasz któreś założenie, zapisz to w raporcie i uzasadnij.

## Skąd pochodzą liczby

| Wielkość | Źródło |
|---|---|
| Liczby zamówień, zdarzeń, klientów, produktów | `uv run novacart info` (generator v0.1.0) |
| Rozmiar w Parquet (zstd) | `novacart info`: ~55 B na zdarzenie clickstream, ~80 B na zamówienie |
| Rozmiar w JSON | Pomiar na skali S, seed 42: średnio ~735 B na zdarzenie clickstream, ~700 B na zamówienie (`to_json` w DuckDB) |
| Zmiany CDC | Skala S: 93 516 zdarzeń CDC dla 24 506 zamówień → ~3,8 zmiany na zamówienie |
| Black Friday | Generator: ×2,8 względem typowego dnia; w danych S: 1046 zamówień vs mediana 7 dni 333 (×3,1) |
| Wzrost | Generator: 35% rok do roku (`growth_per_year = 0.35`) |
| Rozkład dobowy | Szczyt wieczorem; przyjmij, że najgorętsza godzina to ~9% ruchu dobowego, a chwilowe skoki w obrębie godziny ×3 |

## Dziś: skala L (2 lata historii)

| Wielkość | Wartość |
|---|---|
| Okres | 730 dni (2024–2025) |
| Klienci / produkty / sprzedawcy | 2 mln / 200 tys. / 8 tys. |
| Zamówienia łącznie | ~10,2 mln |
| Zamówienia: średnio na dzień / Black Friday | ~14 tys. / ~42 tys. |
| Zdarzenia clickstream łącznie | ~783 mln |
| Zdarzenia: średnio na dzień / Black Friday | ~1,1 mln / ~3,2 mln |
| Zdarzenia na sekundę: szczytowa godzina BF / chwilowy skok | ~80 / ~250 |
| Clickstream na dysku: Parquet / surowy JSON | ~43 GB / ~0,6 TB |
| Zdarzenia CDC (zamówienia) | ~39 mln |
| Pliki od przewoźników | 3 dziennie (~2,2 tys. łącznie) |

## Plan na 3 lata: skala XL (×10)

| Wielkość | Wartość |
|---|---|
| Okres | 1095 dni |
| Klienci / produkty / sprzedawcy | 10 mln / 1 mln / 30 tys. |
| Zamówienia łącznie | ~109 mln |
| Zamówienia: średnio na dzień / Black Friday | ~100 tys. / ~300 tys. |
| Zdarzenia clickstream łącznie | ~8,4 mld |
| Zdarzenia: średnio na dzień / Black Friday | ~7,6 mln / ~23 mln |
| Zdarzenia na sekundę: szczytowa godzina BF / chwilowy skok | ~580 / ~1 700 |
| Clickstream na dysku: Parquet / surowy JSON | ~460 GB / ~6,1 TB |
| Zdarzenia CDC (zamówienia) | ~415 mln |
| Retencja wymagana przez finanse / prawo | zamówienia i płatności: 5 lat; clickstream surowy: 13 miesięcy; dane osobowe: do wniosku RODO (usunięcie w ciągu 30 dni) |

## Założenia o konsumentach

| Konsument | Założenie |
|---|---|
| Dashboardy operacyjne | 50 dashboardów, odświeżanie co 15 min w godzinach 6–22, każde odświeżenie czyta dane z ostatnich 7 dni |
| Raport przychodu | 1 raz dziennie + ok. 200 zapytań ad hoc analityków dziennie |
| Model rekomendacji | trening raz dziennie na 90 dniach clickstreamu i zamówień |
| Wykrywanie anomalii | ciągłe, z opóźnieniem ≤ 15 min |

## Założenia kosztowe, które musisz uzupełnić

Ceny chmurowe zmieniają się. Wpisz aktualne wartości z cennika z datą odczytu albo oznacz własne założenie.

| Pozycja | Twoja wartość | Źródło / data |
|---|---|---|
| Koszt pełnego etatu (FTE) inżyniera danych, rocznie | | |
| BigQuery: cena za TiB skanowany (on-demand) w Twoim regionie | | |
| BigQuery: storage aktywny i długoterminowy, za GiB/miesiąc | | |
| Cloud Storage: Standard w Twoim regionie, za GB/miesiąc | | |
| Dataflow / Dataproc Serverless: rząd wielkości za vCPU-godzinę | | |
| Pub/Sub: za TiB przesłanych danych | | |
| 2010: serwer dla Hadoopa (12 dysków, 2 CPU) | | założenie |
| 2010: appliance MPP (najmniejsza konfiguracja) | | założenie |
| 2010: centrum danych (zasilanie, chłodzenie, szafa) za rok | | założenie |
