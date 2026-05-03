-- Sub-ledger raw tables. Mirror the shape of typical ERP exports
-- (Oracle/SAP/NetSuite). All amounts stored in both transaction currency
-- and USD (the reporting currency).

-- ========================================================================
-- ACCOUNTS PAYABLE
-- ========================================================================
CREATE TABLE IF NOT EXISTS raw.ap_invoices (
    invoice_id           TEXT        PRIMARY KEY,
    vendor_id            TEXT        NOT NULL,
    entity_id            INTEGER     NOT NULL REFERENCES raw.dim_entity(entity_id),
    invoice_date         DATE        NOT NULL,
    posting_date         DATE        NOT NULL,
    due_date             DATE        NOT NULL,
    currency             CHAR(3)     NOT NULL,
    amount_currency      NUMERIC(18,2) NOT NULL,
    amount_usd           NUMERIC(18,2) NOT NULL,
    fx_rate              NUMERIC(18,8) NOT NULL,
    expense_account_code TEXT        NOT NULL,
    control_account_code TEXT        NOT NULL,
    status               TEXT        NOT NULL CHECK (status IN ('OPEN','PAID','VOID','HOLD')),
    description          TEXT,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ap_invoices_posting_date ON raw.ap_invoices(posting_date, entity_id);

CREATE TABLE IF NOT EXISTS raw.ap_payments (
    payment_id           TEXT        PRIMARY KEY,
    invoice_id           TEXT        REFERENCES raw.ap_invoices(invoice_id),
    entity_id            INTEGER     NOT NULL REFERENCES raw.dim_entity(entity_id),
    payment_date         DATE        NOT NULL,
    posting_date         DATE        NOT NULL,
    currency             CHAR(3)     NOT NULL,
    amount_currency      NUMERIC(18,2) NOT NULL,
    amount_usd           NUMERIC(18,2) NOT NULL,
    fx_rate              NUMERIC(18,8) NOT NULL,
    cash_account_code    TEXT        NOT NULL,
    control_account_code TEXT        NOT NULL,
    method               TEXT        NOT NULL CHECK (method IN ('ACH','WIRE','CHECK','CARD')),
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ap_payments_posting_date ON raw.ap_payments(posting_date, entity_id);

CREATE TABLE IF NOT EXISTS raw.ap_accruals (
    accrual_id           TEXT        PRIMARY KEY,
    entity_id            INTEGER     NOT NULL REFERENCES raw.dim_entity(entity_id),
    accrual_date         DATE        NOT NULL,
    posting_date         DATE        NOT NULL,
    reversal_date        DATE        NOT NULL,
    currency             CHAR(3)     NOT NULL,
    amount_currency      NUMERIC(18,2) NOT NULL,
    amount_usd           NUMERIC(18,2) NOT NULL,
    fx_rate              NUMERIC(18,8) NOT NULL,
    expense_account_code TEXT        NOT NULL,
    control_account_code TEXT        NOT NULL,
    description          TEXT,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ========================================================================
-- ACCOUNTS RECEIVABLE
-- ========================================================================
CREATE TABLE IF NOT EXISTS raw.ar_invoices (
    invoice_id           TEXT        PRIMARY KEY,
    customer_id          TEXT        NOT NULL,
    entity_id            INTEGER     NOT NULL REFERENCES raw.dim_entity(entity_id),
    invoice_date         DATE        NOT NULL,
    posting_date         DATE        NOT NULL,
    due_date             DATE        NOT NULL,
    currency             CHAR(3)     NOT NULL,
    amount_currency      NUMERIC(18,2) NOT NULL,
    amount_usd           NUMERIC(18,2) NOT NULL,
    fx_rate              NUMERIC(18,8) NOT NULL,
    revenue_account_code TEXT        NOT NULL,
    control_account_code TEXT        NOT NULL,
    status               TEXT        NOT NULL CHECK (status IN ('OPEN','PAID','VOID','WRITTEN_OFF')),
    description          TEXT,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ar_invoices_posting_date ON raw.ar_invoices(posting_date, entity_id);

CREATE TABLE IF NOT EXISTS raw.ar_receipts (
    receipt_id           TEXT        PRIMARY KEY,
    invoice_id           TEXT        REFERENCES raw.ar_invoices(invoice_id),
    entity_id            INTEGER     NOT NULL REFERENCES raw.dim_entity(entity_id),
    receipt_date         DATE        NOT NULL,
    posting_date         DATE        NOT NULL,
    currency             CHAR(3)     NOT NULL,
    amount_currency      NUMERIC(18,2) NOT NULL,
    amount_usd           NUMERIC(18,2) NOT NULL,
    fx_rate              NUMERIC(18,8) NOT NULL,
    cash_account_code    TEXT        NOT NULL,
    control_account_code TEXT        NOT NULL,
    method               TEXT        NOT NULL CHECK (method IN ('ACH','WIRE','CHECK','CARD')),
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ar_receipts_posting_date ON raw.ar_receipts(posting_date, entity_id);

CREATE TABLE IF NOT EXISTS raw.ar_credit_memos (
    memo_id              TEXT        PRIMARY KEY,
    invoice_id           TEXT        REFERENCES raw.ar_invoices(invoice_id),
    entity_id            INTEGER     NOT NULL REFERENCES raw.dim_entity(entity_id),
    memo_date            DATE        NOT NULL,
    posting_date         DATE        NOT NULL,
    currency             CHAR(3)     NOT NULL,
    amount_currency      NUMERIC(18,2) NOT NULL,
    amount_usd           NUMERIC(18,2) NOT NULL,
    fx_rate              NUMERIC(18,8) NOT NULL,
    reason               TEXT        NOT NULL CHECK (reason IN ('RETURN','PRICE_ADJ','WRITE_OFF')),
    revenue_account_code TEXT        NOT NULL,
    control_account_code TEXT        NOT NULL,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ========================================================================
-- INVENTORY
-- ========================================================================
CREATE TABLE IF NOT EXISTS raw.inv_transactions (
    txn_id                TEXT        PRIMARY KEY,
    item_id               TEXT        NOT NULL,
    entity_id             INTEGER     NOT NULL REFERENCES raw.dim_entity(entity_id),
    txn_date              DATE        NOT NULL,
    posting_date          DATE        NOT NULL,
    txn_type              TEXT        NOT NULL CHECK (txn_type IN ('RECEIPT','COGS','ADJUSTMENT')),
    quantity              NUMERIC(18,4) NOT NULL,
    unit_cost_usd         NUMERIC(18,4) NOT NULL,
    amount_usd            NUMERIC(18,2) NOT NULL,
    inventory_account_code TEXT       NOT NULL,
    offset_account_code   TEXT        NOT NULL,
    description           TEXT,
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_inv_txn_posting_date ON raw.inv_transactions(posting_date, entity_id);
