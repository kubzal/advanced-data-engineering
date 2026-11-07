# Moduł 01 — przykłady kodu

Wszystkie przykłady działają lokalnie, bez chmury i bez kosztów. Modelują mechanizmy z kolejnych epok (układ kolumnowy, dystrybucja MPP, MapReduce, log transakcji, skalowanie architektur) na danych NovaCart w małej skali. Dzięki temu efekt widać w sekundach na laptopie.

## Przygotowanie

```bash
# z katalogu głównego repozytorium
cd datasets && uv sync && uv run novacart generate --scale s --components all -o ../data/s && cd ..

cd modules/01-ewolucja-architektur-danych/examples
uv sync                                    # duckdb, pyarrow, numpy
uv run python 01_row_vs_column.py
```

Skrypty szukają danych w `data/s` w katalogu głównym repozytorium. Inną lokalizację wskażesz zmienną `NOVACART_DATA`, np. `NOVACART_DATA=../../../data/xs uv run python 02_mpp_hash_distribution.py`. Pliki tymczasowe trafiają do katalogu tymczasowego systemu i są usuwane po zakończeniu.

## Przykłady

| Plik | Lekcja | Co pokazuje | Czas (skala S) |
|---|---|---|---|
| `01_row_vs_column.py` | [01.01](../01-oltp-vs-olap.md#5--w-praktyce) | SQLite (*row store* z B-drzewem) vs DuckDB (*column store*): odczyt po kluczu, UPDATE z COMMIT, agregacja, rozmiar na dysku | ~5 s |
| `02_mpp_hash_distribution.py` | [01.02](../02-era-hurtowni-danych.md#5--w-praktyce) | Rozkład wierszy na węzły MPP dla różnych kluczy dystrybucji, *skew*, koszt redystrybucji i *broadcast* przy JOIN | < 1 s |
| `03_mapreduce_from_scratch.py` | [01.03](../03-era-big-data.md#5--w-praktyce) | MapReduce od zera: *map*, *partition*, *sort/spill*, *shuffle*, *merge*, *reduce*; bajty *shuffle* z *combinerem* i bez | ~1–2 s |
| `04_schema_on_read.py` | [01.03](../03-era-big-data.md#5--w-praktyce) | Pliki QuickShip ze zmianą schematu: *schema-on-write* (odrzucenie) vs naiwne *schema-on-read* (ciche błędne liczby) | ~4 s |
| `05_storage_compute_economics.py` | [01.04](../04-era-cloud-data-warehouse.md#5--w-praktyce) | Model kosztowy: stały klaster vs płatność za bajty vs płatność za czas *warehouse* dla różnych profili obciążenia | < 1 s |
| `06_toy_table_format.py` | [01.05](../05-era-lakehouse.md#5--w-praktyce) | Minimalny *table format*: log JSON, atomowy commit (*put-if-absent*), *optimistic concurrency* na dwóch procesach, *time travel* | ~1 s |
| `07_data_product_contract.py` | [01.06](../06-kierunki-organizacyjne-i-trendy.md#5--w-praktyce) | Kontrakt produktu danych `orders` sprawdzany w DuckDB; wykrywa anomalię cen w groszach | < 1 s |
| `08_parallel_architectures_sim.py` | [01.07](../07-architektury-rownoleglego-przetwarzania.md#5--w-praktyce) | Model skalowania shared-memory / shared-disk / shared-nothing / shared-data, rebalancing `hash mod N` vs *consistent hashing* | < 1 s |

Lekcja [01.08](../08-role-w-zespolach-danych.md) nie ma przykładu kodu: jej część praktyczna to macierz RACI i analiza incydentu.

> [!NOTE]
> Czasy zmierzono na laptopie z Apple Silicon. Na Twojej maszynie będą inne, ale **proporcje** między wariantami (o nie chodzi w przykładach) powinny być podobne. Wyniki `06_toy_table_format.py` dotyczące liczby kolizji zmieniają się między uruchomieniami, bo zależą od szeregowania procesów. Liczba utraconych commitów zawsze wynosi 0.

## Sprzątanie

Przykłady nie tworzą zasobów w chmurze ani trwałych plików. Żeby usunąć lokalne środowisko Pythona:

```bash
rm -rf .venv
```
