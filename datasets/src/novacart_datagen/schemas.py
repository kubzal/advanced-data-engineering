"""Schematy wszystkich zbiorów danych NovaCart (z opisami kolumn) i ich eksport.

Opisy kolumn trafiają do metadanych Parquet oraz do eksportowanych schematów BigQuery.
Przydają się w modułach o katalogach danych (moduł 30).
"""

from __future__ import annotations

import json
from typing import Any

import pyarrow as pa

from .arrays import MONEY_TYPE, TS_TYPE

STR, I32, I64, F64, BOOL, DATE = pa.string(), pa.int32(), pa.int64(), pa.float64(), pa.bool_(), pa.date32()


def F(name: str, type_: pa.DataType, nullable: bool, description: str, pii: bool = False) -> pa.Field:
    meta = {"description": description}
    if pii:
        meta["pii"] = "true"
    return pa.field(name, type_, nullable=nullable, metadata=meta)


def S(description: str, *fields: pa.Field) -> pa.Schema:
    return pa.schema(list(fields), metadata={"description": description})


SCHEMAS: dict[str, pa.Schema] = {
    "customers": S(
        "Klienci NovaCart: stan na koniec okresu (pełny eksport z bazy transakcyjnej).",
        F("customer_id", I64, False, "Identyfikator klienta (klucz główny)."),
        F("first_name", STR, True, "Imię. NULL po realizacji wniosku RODO.", True),
        F("last_name", STR, True, "Nazwisko. NULL po realizacji wniosku RODO.", True),
        F("email", STR, True, "Adres e-mail (domeny .example). Nie jest unikalny.", True),
        F("phone", STR, True, "Telefon w formacie E.164; część rekordów zawiera spację po prefiksie.", True),
        F("birth_date", DATE, True, "Data urodzenia.", True),
        F("country", STR, False, "Kod kraju ISO 3166-1 alpha-2."),
        F("city", STR, False, "Miasto (aktualny adres)."),
        F("postal_code", STR, True, "Kod pocztowy w formacie lokalnym.", True),
        F("street_address", STR, True, "Ulica i numer.", True),
        F("marketing_consent", BOOL, False, "Zgoda marketingowa."),
        F("created_at", TS_TYPE, False, "Moment rejestracji."),
        F("updated_at", TS_TYPE, False, "Ostatnia zmiana rekordu."),
        F("gdpr_erased_at", TS_TYPE, True, "Moment anonimizacji danych (RODO), jeśli nastąpiła."),
    ),
    "sellers": S(
        "Sprzedawcy marketplace'u.",
        F("seller_id", I64, False, "Identyfikator sprzedawcy."),
        F("name", STR, False, "Nazwa firmy (fikcyjna)."),
        F("country", STR, False, "Kraj siedziby."),
        F("city", STR, False, "Miasto magazynu, z którego wysyłane są paczki."),
        F("tier", STR, False, "Pakiet współpracy: standard, pro, premium."),
        F("rating", F64, False, "Średnia ocena sprzedawcy (1–5)."),
        F("commission_rate", pa.decimal128(5, 2), False, "Prowizja NovaCart w procentach."),
        F("joined_at", TS_TYPE, False, "Data dołączenia do marketplace'u."),
    ),
    "products": S(
        "Katalog produktów: stan na koniec okresu.",
        F("product_id", I64, False, "Identyfikator produktu."),
        F("sku", STR, False, "Kod SKU."),
        F("name", STR, False, "Nazwa produktu."),
        F("category_id", I32, False, "Kategoria (liść drzewa kategorii)."),
        F("seller_id", I64, False, "Sprzedawca oferujący produkt."),
        F("brand", STR, False, "Marka (fikcyjna)."),
        F(
            "list_price_eur",
            MONEY_TYPE,
            False,
            "Aktualna cena katalogowa w EUR (ceny lokalne liczone kursem stałym).",
        ),
        F("weight_g", I32, False, "Waga produktu w gramach."),
        F("created_at", TS_TYPE, False, "Moment dodania do katalogu."),
        F("updated_at", TS_TYPE, False, "Ostatnia zmiana (np. ceny)."),
    ),
    "categories": S(
        "Dwupoziomowe drzewo kategorii.",
        F("category_id", I32, False, "Identyfikator kategorii (1–99: główne, 100+: liście)."),
        F("parent_category_id", I32, True, "Kategoria nadrzędna; NULL dla kategorii głównych."),
        F("slug", STR, False, "Identyfikator w URL."),
        F("name_pl", STR, False, "Nazwa po polsku."),
        F("name_en", STR, False, "Nazwa po angielsku."),
    ),
    "gdpr_requests": S(
        "Zrealizowane wnioski o usunięcie danych osobowych (RODO art. 17).",
        F("request_id", I64, False, "Identyfikator wniosku."),
        F("customer_id", I64, False, "Klient, którego dotyczy wniosek."),
        F("requested_at", TS_TYPE, False, "Moment złożenia wniosku."),
        F("completed_at", TS_TYPE, False, "Moment anonimizacji w bazie transakcyjnej."),
        F("channel", STR, False, "Kanał złożenia wniosku."),
    ),
    "orders": S(
        "Zamówienia: stan na koniec okresu. Partycjonowane po dacie złożenia (UTC).",
        F("order_id", I64, False, "Identyfikator zamówienia."),
        F("customer_id", I64, False, "Klient."),
        F("status", STR, False, "created, paid, shipped, delivered, returned, cancelled."),
        F("currency", STR, False, "Waluta zamówienia (PLN, EUR, CZK)."),
        F("platform", STR, False, "web, android, ios."),
        F("payment_method", STR, False, "card, blik, paypal, bank_transfer, ideal, cod (za pobraniem)."),
        F("promo_code", STR, True, "Kod promocyjny, jeśli użyty."),
        F("items_count", I32, False, "Liczba pozycji zamówienia."),
        F("subtotal_amount", MONEY_TYPE, False, "Suma pozycji przed rabatem."),
        F("discount_amount", MONEY_TYPE, False, "Suma rabatów."),
        F("shipping_amount", MONEY_TYPE, False, "Koszt dostawy."),
        F("total_amount", MONEY_TYPE, False, "Do zapłaty: subtotal - discount + shipping."),
        F("shipping_country", STR, False, "Kraj dostawy."),
        F("shipping_city", STR, False, "Miasto dostawy."),
        F("shipping_postal_code", STR, True, "Kod pocztowy dostawy.", True),
        F("shipping_street", STR, True, "Adres dostawy.", True),
        F("carrier", STR, True, "Przewoźnik (po wysyłce)."),
        F("shipment_id", STR, True, "Numer przesyłki u przewoźnika."),
        F("created_at", TS_TYPE, False, "Złożenie zamówienia."),
        F("paid_at", TS_TYPE, True, "Opłacenie (dla cod: moment doręczenia)."),
        F("shipped_at", TS_TYPE, True, "Nadanie przesyłki."),
        F("delivered_at", TS_TYPE, True, "Doręczenie."),
        F("cancelled_at", TS_TYPE, True, "Anulowanie."),
        F("returned_at", TS_TYPE, True, "Zwrot."),
        F("updated_at", TS_TYPE, False, "Ostatnia zmiana statusu."),
    ),
    "order_items": S(
        "Pozycje zamówień. Partycjonowane po dacie złożenia zamówienia.",
        F("order_id", I64, False, "Zamówienie."),
        F("line_number", I32, False, "Numer pozycji w zamówieniu (od 1)."),
        F("product_id", I64, False, "Produkt."),
        F("seller_id", I64, False, "Sprzedawca."),
        F("category_id", I32, False, "Kategoria produktu w chwili sprzedaży."),
        F("quantity", I32, False, "Liczba sztuk."),
        F("unit_price", MONEY_TYPE, False, "Cena jednostkowa w walucie zamówienia."),
        F("discount_amount", MONEY_TYPE, False, "Rabat na pozycji."),
        F("line_amount", MONEY_TYPE, False, "quantity * unit_price - discount_amount."),
        F("currency", STR, False, "Waluta."),
    ),
    "payments": S(
        "Transakcje płatnicze z bramki płatności (również dostępne przez mock API). Partycjonowane po dacie transakcji.",
        F("payment_id", STR, False, "Identyfikator transakcji w bramce płatności."),
        F("order_id", I64, False, "Zamówienie."),
        F("customer_id", I64, False, "Klient."),
        F("type", STR, False, "charge (obciążenie) lub refund (zwrot środków)."),
        F("status", STR, False, "succeeded lub failed."),
        F("failure_code", STR, True, "Przyczyna odrzucenia."),
        F("method", STR, False, "Metoda płatności."),
        F("card_brand", STR, True, "Marka karty (tylko płatności kartą)."),
        F("card_last4", STR, True, "Ostatnie 4 cyfry karty.", True),
        F("amount", MONEY_TYPE, False, "Kwota w walucie zamówienia (zawsze dodatnia, także dla refund)."),
        F("currency", STR, False, "Waluta."),
        F("payer_email", STR, True, "E-mail płatnika w chwili transakcji.", True),
        F("created_at", TS_TYPE, False, "Moment transakcji."),
    ),
    "clickstream": S(
        "Zdarzenia z aplikacji web i mobilnych. Partycjonowane po dacie PRZYJĘCIA (received_at), nie zdarzenia.",
        F("event_id", STR, False, "Identyfikator zdarzenia (UUID). Duplikaty mają ten sam event_id."),
        F("event_type", STR, False, "Typ zdarzenia; część rekordów ma niepoprawne wartości."),
        F("event_ts", TS_TYPE, False, "Czas zdarzenia według zegara urządzenia (event time)."),
        F("received_at", TS_TYPE, False, "Czas przyjęcia przez kolektor (processing time)."),
        F("session_id", STR, True, "Sesja; NULL w uszkodzonych rekordach."),
        F("anonymous_id", STR, False, "Identyfikator urządzenia/przeglądarki."),
        F("customer_id", I64, True, "Zalogowany klient; NULL dla anonimowych."),
        F("platform", STR, False, "web, android, ios."),
        F("app_version", STR, True, "Wersja aplikacji mobilnej."),
        F("user_agent", STR, False, "User-Agent."),
        F("ip_address", STR, False, "Adres IP klienta.", True),
        F("country", STR, False, "Kraj (z geolokalizacji lub profilu)."),
        F("page_path", STR, False, "Ścieżka strony / ekranu."),
        F("referrer", STR, True, "Strona odsyłająca (tylko pierwsze zdarzenie sesji)."),
        F("utm_source", STR, True, "Źródło kampanii."),
        F("utm_medium", STR, True, "Medium kampanii."),
        F("utm_campaign", STR, True, "Nazwa kampanii."),
        F("product_id", I64, True, "Produkt (zdarzenia produktowe)."),
        F("category_id", I32, True, "Kategoria (strona kategorii lub produkt)."),
        F("search_query", STR, True, "Fraza wyszukiwania (z literówkami)."),
        F("quantity", I32, True, "Liczba sztuk (zdarzenia koszyka)."),
        F("price", MONEY_TYPE, True, "Cena produktu lub wartość zamówienia (purchase)."),
        F("currency", STR, True, "Waluta ceny."),
        F("order_id", I64, True, "Zamówienie (tylko purchase)."),
        F("properties", STR, True, "Dodatkowe atrybuty jako JSON (schema-on-read)."),
    ),
}

# Kolejność kolumn w bazie transakcyjnej (używana przez replay-oltp i DDL)
OLTP_TABLES = ("categories", "sellers", "customers", "products", "orders", "order_items")


def conform(table: pa.Table, name: str) -> pa.Table:
    """Rzutuje tabelę na kanoniczny schemat (kolejność kolumn, typy, metadane)."""
    schema = SCHEMAS[name]
    return pa.table([table.column(f.name).cast(f.type) for f in schema], schema=schema)


# ---------------------------------------------------------------------------
# Eksport schematów
# ---------------------------------------------------------------------------


def _bq_type(t: pa.DataType) -> str:
    if pa.types.is_integer(t):
        return "INTEGER"
    if pa.types.is_floating(t):
        return "FLOAT"
    if pa.types.is_decimal(t):
        return "NUMERIC"
    if pa.types.is_timestamp(t):
        return "TIMESTAMP"
    if pa.types.is_date(t):
        return "DATE"
    if pa.types.is_boolean(t):
        return "BOOLEAN"
    return "STRING"


def bigquery_schema(name: str) -> list[dict[str, Any]]:
    out = []
    for f in SCHEMAS[name]:
        field: dict[str, Any] = {
            "name": f.name,
            "type": _bq_type(f.type),
            "mode": "NULLABLE" if f.nullable else "REQUIRED",
            "description": (f.metadata or {}).get(b"description", b"").decode(),
        }
        if name == "clickstream" and f.name == "properties":
            field["type"] = "JSON"
        out.append(field)
    return out


def _avro_type(t: pa.DataType) -> Any:
    if pa.types.is_int64(t):
        return "long"
    if pa.types.is_integer(t):
        return "int"
    if pa.types.is_floating(t):
        return "double"
    if pa.types.is_boolean(t):
        return "boolean"
    if pa.types.is_decimal(t):
        return {"type": "bytes", "logicalType": "decimal", "precision": t.precision, "scale": t.scale}
    if pa.types.is_timestamp(t):
        return {"type": "long", "logicalType": "timestamp-micros"}
    if pa.types.is_date(t):
        return {"type": "int", "logicalType": "date"}
    return "string"


def avro_schema(name: str) -> dict[str, Any]:
    fields = []
    for f in SCHEMAS[name]:
        t = _avro_type(f.type)
        doc = (f.metadata or {}).get(b"description", b"").decode()
        if f.nullable:
            fields.append({"name": f.name, "type": ["null", t], "default": None, "doc": doc})
        else:
            fields.append({"name": f.name, "type": t, "doc": doc})
    return {"type": "record", "name": name, "namespace": "com.novacart", "fields": fields}


def export_schemas(fmt: str) -> dict[str, str]:
    """Zwraca {nazwa_pliku: zawartość} dla wszystkich zbiorów w danym formacie."""
    files = {}
    for name in SCHEMAS:
        if fmt == "bigquery":
            files[f"{name}.json"] = json.dumps(bigquery_schema(name), indent=2, ensure_ascii=False)
        elif fmt == "avro":
            files[f"{name}.avsc"] = json.dumps(avro_schema(name), indent=2, ensure_ascii=False)
        elif fmt == "arrow":
            files[f"{name}.txt"] = SCHEMAS[name].to_string(show_field_metadata=True)
        else:
            raise ValueError(f"Nieznany format schematu: {fmt}")
    return files
