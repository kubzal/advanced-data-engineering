<!--
AUTOR: Indeks przykładów kodu modułu. Każdy plik z przykładem ma tu wpis.
Nazwy plików: NN_opis.ext, gdzie NN to kolejność użycia w lekcjach (01_, 02_, …).
-->

# Moduł {{NN}} — przykłady kodu

## Przygotowanie

```bash
# z katalogu głównego repozytorium
cd datasets && uv run novacart generate --scale {{s}} --components {{…}} -o ../data/{{NN}} && cd ..

cd modules/{{NN-slug}}/examples
uv sync                      # jeśli przykłady mają własny pyproject.toml
export GOOGLE_CLOUD_PROJECT={{twój-projekt}}
```

## Przykłady

| Plik | Lekcja | Co pokazuje | Wymaga chmury | Szacowany koszt |
|---|---|---|---|---|
| `01_{{nazwa}}.sql` | [{{NN}}.01](../01-nazwa-lekcji.md#5--w-praktyce) | {{…}} | {{BigQuery}} | {{< 0,01 USD}} |
| `02_{{nazwa}}.py` | [{{NN}}.02]({{…}}) | {{…}} | {{nie (DuckDB)}} | 0 |
| `terraform/` | [{{NN}}.03]({{…}}) | {{infrastruktura do przykładów}} | {{tak}} | {{…}} |

## Sprzątanie

```bash
{{polecenia usuwające wszystkie zasoby utworzone przez przykłady, np.:}}
{{terraform -chdir=terraform destroy -auto-approve}}
{{bq rm -r -f -d $GOOGLE_CLOUD_PROJECT:novacart_m{{NN}}}}
```

> [!CAUTION]
> Uruchom sprzątanie po zakończeniu modułu. Zasoby z etykietą `module={{NN}}` możesz znaleźć poleceniem
> `gcloud asset search-all-resources --query="labels.module={{NN}}"`.
