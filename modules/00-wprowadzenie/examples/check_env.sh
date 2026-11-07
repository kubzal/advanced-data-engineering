#!/usr/bin/env bash
# examples/check_env.sh
# Sprawdza, czy na Twojej maszynie są narzędzia potrzebne w kursie.
# Niczego nie instaluje i niczego nie zmienia. Kod wyjścia 1 = brakuje narzędzia wymaganego.
#
#   bash examples/check_env.sh

set -uo pipefail

missing_required=0

# Wersja pierwszej linii wyjścia polecenia, bez znaków sterujących.
first_line() { "$@" 2>&1 | head -n 1 | tr -d '\r'; }

# check <wymagane|opcjonalne> <nazwa> <polecenie wersji...>
check() {
  local level="$1" name="$2"; shift 2
  if command -v "$name" >/dev/null 2>&1; then
    printf "  ✅ %-10s %s\n" "$name" "$(first_line "$@")"
  elif [[ "$level" == "wymagane" ]]; then
    printf "  ❌ %-10s BRAK (wymagane)\n" "$name"
    missing_required=1
  else
    printf "  ⚪ %-10s brak (opcjonalne)\n" "$name"
  fi
}

# Porównanie wersji w formacie X.Y: version_ge 3.13 3.12 -> prawda
version_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n 1)" == "$2" ]]; }

echo "== Narzędzia wymagane =="
check wymagane gcloud    gcloud --version
check wymagane bq        bq version
check wymagane terraform terraform version
check wymagane uv        uv --version
check wymagane python3   python3 --version
check wymagane git       git --version
check wymagane docker    docker --version

echo "== Narzędzia opcjonalne =="
check opcjonalne tofu    tofu version
check opcjonalne duckdb  duckdb --version
check opcjonalne java    java -version
check opcjonalne kubectl kubectl version --client
check opcjonalne jq      jq --version
check opcjonalne colima  colima version

echo "== Szczegóły =="

# Python: kurs wymaga 3.12+
if command -v python3 >/dev/null 2>&1; then
  py="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if version_ge "$py" "3.12"; then
    echo "  ✅ Python $py (>= 3.12)"
  else
    echo "  ⚠️  Python $py jest za stary; uv zainstaluje 3.12+ dla projektów kursu (uv python install 3.12)"
  fi
fi

# Terraform: kurs zakłada 1.9+
if command -v terraform >/dev/null 2>&1; then
  tf="$(terraform version -json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["terraform_version"])' 2>/dev/null)"
  if [[ -n "$tf" ]] && version_ge "$tf" "1.9"; then
    echo "  ✅ Terraform $tf (>= 1.9)"
  else
    echo "  ⚠️  Terraform ${tf:-?}: kurs zakłada 1.9+"
  fi
fi

# Docker: sam klient to za mało, potrzebny jest działający daemon (Docker Desktop / Colima)
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    echo "  ✅ Docker daemon działa"
  else
    echo "  ⚠️  Docker daemon nie działa: uruchom Docker Desktop albo 'colima start'"
  fi
fi

# DuckDB: wystarczy pakiet Pythona, CLI jest wygodne, ale opcjonalne
if command -v uv >/dev/null 2>&1; then
  ddb="$(cd "$(dirname "$0")" && env -u VIRTUAL_ENV uv run --quiet python -c 'import duckdb; print(duckdb.__version__)' 2>/dev/null)"
  if [[ -n "$ddb" ]]; then
    echo "  ✅ DuckDB (pakiet Pythona) $ddb"
  else
    echo "  ⚠️  Pakiet duckdb niedostępny: uruchom 'uv sync' w katalogu examples/"
  fi
fi

# gcloud: aktywne konto, projekt i ADC. Pokazujemy tylko metadane, nigdy tokeny.
if command -v gcloud >/dev/null 2>&1; then
  account="$(gcloud config get-value account 2>/dev/null)"
  project="$(gcloud config get-value project 2>/dev/null)"
  config="$(gcloud config configurations list --filter=is_active=true --format='value(name)' 2>/dev/null)"
  echo "  ℹ️  gcloud: konfiguracja='${config:-?}', konto='${account:-(brak)}', projekt='${project:-(brak)}'"
  adc="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}/application_default_credentials.json"
  if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" && "${GOOGLE_APPLICATION_CREDENTIALS}" != "$adc" ]]; then
    echo "  ⚠️  GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS} ma pierwszeństwo przed plikiem ADC z gcloud"
  elif [[ -f "$adc" ]]; then
    adc_type="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("type","?"))' "$adc" 2>/dev/null)"
    echo "  ✅ ADC: $adc (type=$adc_type)"
  else
    echo "  ⚠️  ADC nie skonfigurowane: gcloud auth application-default login (lekcja 00.04)"
  fi
fi

echo
if [[ "$missing_required" -eq 0 ]]; then
  echo "Wynik: wszystkie wymagane narzędzia są zainstalowane."
else
  echo "Wynik: brakuje wymaganych narzędzi (❌). Instrukcje: lekcja 00.04."
fi
exit "$missing_required"
