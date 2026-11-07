#!/usr/bin/env bash
# examples/07_generate_and_inspect.sh
# Generuje dane NovaCart i pokazuje, co powstało: manifest, liczności, anomalie, rozmiary.
#
#   bash examples/07_generate_and_inspect.sh            # skala s, seed 42, katalog data/s
#   SCALE=xs OUT=data/xs bash examples/07_generate_and_inspect.sh
#
# Uruchamiaj z dowolnego miejsca: ścieżki są liczone względem katalogu głównego repozytorium.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCALE="${SCALE:-s}"
SEED="${SEED:-42}"
OUT="${OUT:-data/${SCALE}}"
COMPONENTS="${COMPONENTS:-entities,orders,clickstream,partners}"
case "$OUT" in /*) OUT_ABS="$OUT" ;; *) OUT_ABS="${REPO_ROOT}/${OUT}" ;; esac

# uv nie powinien używać „cudzego” aktywnego virtualenv (np. z pyenv)
unset VIRTUAL_ENV

cd "${REPO_ROOT}/datasets"
uv sync --quiet

echo "== 1. Skale dostępne w generatorze =="
uv run novacart info

echo
echo "== 2. Generowanie: skala=${SCALE}, seed=${SEED} -> ${OUT_ABS} =="
time uv run novacart generate --scale "$SCALE" --seed "$SEED" \
  --components "$COMPONENTS" -o "$OUT_ABS" --overwrite

echo
echo "== 3. Manifest: konfiguracja i liczności =="
python3 - "$OUT_ABS/_manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
cfg = m["config"]
print(f"wersja generatora {m['version']}, czas {m['duration_seconds']} s")
print(f"okres {cfg['start_date']} .. {cfg['end_date']} ({cfg['days']} dni), seed {cfg['seed']}")
for name, n in sorted(m["row_counts"].items()):
    print(f"  {name:<28}{n:>12,}")
PY

echo
echo "== 4. Anomalie wstrzyknięte w dane (ściąga do modułu 29) =="
python3 - "$OUT_ABS/_manifest.json" <<'PY'
import json, sys
for a in json.load(open(sys.argv[1]))["anomalies"]:
    print(f"  {a['date']}  {a['kind']:<36} {a['description']}")
PY

echo
echo "== 5. Rozmiar na dysku per tabela =="
(cd "$OUT_ABS" && du -sh -- */ | sort -h)

echo
echo "== 6. Partycje: jedna partycja dzienna = jeden plik =="
(cd "$OUT_ABS" && find orders -name '*.parquet' | sort | head -n 3)
printf '... razem %s plików w orders/\n' "$(find "$OUT_ABS/orders" -name '*.parquet' | wc -l | tr -d ' ')"

echo
echo "== 7. Odcisk palca danych (porównaj z innymi uczestnikami kursu) =="
# Ten sam seed i parametry => identyczne bajty, więc identyczny skrót SHA-256.
(cd "$OUT_ABS" && find orders -name '*.parquet' | sort | xargs cat | shasum -a 256 | cut -c1-16)
