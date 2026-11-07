# Kod startowy — Trzy epoki, jedna NovaCart

To zadanie jest koncepcyjne, więc „kod startowy” to szablony dokumentów. Oszczędzają Ci pracy nad formą, żebyś mógł(a) skupić się na decyzjach. Nie zawierają rozwiązania.

## Zawartość

| Plik | Opis | Do uzupełnienia? |
|---|---|---|
| [`zalozenia-wolumenowe.md`](zalozenia-wolumenowe.md) | Wspólne liczby: wolumeny dla skal L i XL, szczyty, konsumenci; tabela cen do uzupełnienia | tak, tylko tabela cen |
| [`warianty-template.md`](warianty-template.md) | Szablon opisu jednego wariantu architektury (skopiuj 3 razy) | tak, `TODO(zadanie)` |
| [`adr-template.md`](adr-template.md) | Szablon ADR w formacie Nygard/MADR | tak, `TODO(zadanie)` |

## Uruchomienie

```bash
# 1. Skopiuj szablony do katalogu z rozwiązaniem
cd modules/01-ewolucja-architektur-danych/exercise
cp starter/warianty-template.md warianty.md
cp starter/adr-template.md adr-001-platforma-danych.md

# 2. (Opcjonalnie) zweryfikuj liczby z arkusza założeń
cd ../../../datasets
uv run novacart info
uv run novacart generate --scale s --seed 42 --components all -o ../data/s
```

W tym zadaniu nie ma automatycznych testów. Zadanie jest ukończone, gdy spełnione są wszystkie [kryteria akceptacji](../README.md#kryteria-akceptacji). Szybki autotest: wyszukaj w swoich plikach `TODO(zadanie)`. Nie powinno zostać żadne wystąpienie.

```bash
grep -rn "TODO(zadanie)" warianty.md adr-001-platforma-danych.md || echo "OK: brak TODO"
```
