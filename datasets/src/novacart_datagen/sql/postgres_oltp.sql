-- =============================================================================
-- NovaCart — schemat bazy transakcyjnej (PostgreSQL 14+)
--
-- Używany przez `novacart replay-oltp --init-schema` oraz w modułach 25–26
-- (Cloud SQL / AlloyDB jako źródło CDC dla Datastream i Debezium).
-- =============================================================================

CREATE TABLE IF NOT EXISTS categories (
    category_id         integer      PRIMARY KEY,
    parent_category_id  integer      REFERENCES categories (category_id),
    slug                text         NOT NULL UNIQUE,
    name_pl             text         NOT NULL,
    name_en             text         NOT NULL
);

CREATE TABLE IF NOT EXISTS sellers (
    seller_id           bigint       PRIMARY KEY,
    name                text         NOT NULL,
    country             char(2)      NOT NULL,
    city                text         NOT NULL,
    tier                text         NOT NULL CHECK (tier IN ('standard', 'pro', 'premium')),
    rating              double precision NOT NULL,
    commission_rate     numeric(5,2) NOT NULL,
    joined_at           timestamptz  NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id         bigint       PRIMARY KEY,
    first_name          text,
    last_name           text,
    email               text,                    -- celowo bez UNIQUE: duplikaty kont istnieją
    phone               text,
    birth_date          date,
    country             char(2)      NOT NULL,
    city                text         NOT NULL,
    postal_code         text,
    street_address      text,
    marketing_consent   boolean      NOT NULL,
    created_at          timestamptz  NOT NULL,
    updated_at          timestamptz  NOT NULL,
    gdpr_erased_at      timestamptz
);

CREATE TABLE IF NOT EXISTS products (
    product_id          bigint       PRIMARY KEY,
    sku                 text         NOT NULL UNIQUE,
    name                text         NOT NULL,
    category_id         integer      NOT NULL REFERENCES categories (category_id),
    seller_id           bigint       NOT NULL REFERENCES sellers (seller_id),
    brand               text         NOT NULL,
    list_price_eur      numeric(12,2) NOT NULL,
    weight_g            integer      NOT NULL,
    created_at          timestamptz  NOT NULL,
    updated_at          timestamptz  NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id            bigint       PRIMARY KEY,
    customer_id         bigint       NOT NULL REFERENCES customers (customer_id),
    status              text         NOT NULL
        CHECK (status IN ('created', 'paid', 'shipped', 'delivered', 'returned', 'cancelled')),
    currency            char(3)      NOT NULL,
    platform            text         NOT NULL,
    payment_method      text         NOT NULL,
    promo_code          text,
    items_count         integer      NOT NULL,
    subtotal_amount     numeric(12,2) NOT NULL,
    discount_amount     numeric(12,2) NOT NULL,
    shipping_amount     numeric(12,2) NOT NULL,
    total_amount        numeric(12,2) NOT NULL,
    shipping_country    char(2)      NOT NULL,
    shipping_city       text         NOT NULL,
    shipping_postal_code text,
    shipping_street     text,
    carrier             text,
    shipment_id         text,
    created_at          timestamptz  NOT NULL,
    paid_at             timestamptz,
    shipped_at          timestamptz,
    delivered_at        timestamptz,
    cancelled_at        timestamptz,
    returned_at         timestamptz,
    updated_at          timestamptz  NOT NULL
);

CREATE INDEX IF NOT EXISTS orders_customer_idx ON orders (customer_id);
CREATE INDEX IF NOT EXISTS orders_updated_idx ON orders (updated_at);

CREATE TABLE IF NOT EXISTS order_items (
    order_id            bigint       NOT NULL REFERENCES orders (order_id),
    line_number         integer      NOT NULL,
    product_id          bigint       NOT NULL REFERENCES products (product_id),
    seller_id           bigint       NOT NULL REFERENCES sellers (seller_id),
    quantity            integer      NOT NULL,
    unit_price          numeric(12,2) NOT NULL,
    discount_amount     numeric(12,2) NOT NULL,
    line_amount         numeric(12,2) NOT NULL,
    currency            char(3)      NOT NULL,
    PRIMARY KEY (order_id, line_number)
);

-- Pełny obraz wiersza "before" w strumieniu zmian (Debezium/Datastream).
ALTER TABLE categories  REPLICA IDENTITY FULL;
ALTER TABLE sellers     REPLICA IDENTITY FULL;
ALTER TABLE customers   REPLICA IDENTITY FULL;
ALTER TABLE products    REPLICA IDENTITY FULL;
ALTER TABLE orders      REPLICA IDENTITY FULL;
ALTER TABLE order_items REPLICA IDENTITY FULL;

-- -----------------------------------------------------------------------------
-- Opcjonalnie (wymaga uprawnień i wal_level = logical; w Cloud SQL flaga
-- cloudsql.logical_decoding = on). Uruchom ręcznie przed konfiguracją CDC:
--
--   CREATE PUBLICATION novacart_pub FOR ALL TABLES;
--   SELECT pg_create_logical_replication_slot('novacart_slot', 'pgoutput');
-- -----------------------------------------------------------------------------
