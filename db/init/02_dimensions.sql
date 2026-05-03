-- Reference / dimension tables loaded from synthetic CSVs.
-- These live in `raw` for now; dbt will project them into staging/intermediate.

CREATE TABLE IF NOT EXISTS raw.dim_entity (
    entity_id            INTEGER     PRIMARY KEY,
    entity_code          TEXT        NOT NULL UNIQUE,
    entity_name          TEXT        NOT NULL,
    functional_currency  CHAR(3)     NOT NULL,
    country              TEXT        NOT NULL,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.dim_account (
    account_id            INTEGER     PRIMARY KEY,
    account_code          TEXT        NOT NULL UNIQUE,
    account_name          TEXT        NOT NULL,
    account_type          TEXT        NOT NULL CHECK (account_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE')),
    parent_account_code   TEXT,
    is_control_account    BOOLEAN     NOT NULL DEFAULT FALSE,
    subledger_source      TEXT        CHECK (subledger_source IN ('AP','AR','INV') OR subledger_source IS NULL),
    effective_from        DATE        NOT NULL,
    effective_to          DATE,
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.fx_rate (
    rate_date         DATE        NOT NULL,
    from_currency     CHAR(3)     NOT NULL,
    to_currency       CHAR(3)     NOT NULL,
    rate              NUMERIC(18,8) NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rate_date, from_currency, to_currency)
);
