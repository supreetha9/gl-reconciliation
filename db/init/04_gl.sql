-- General Ledger journal entries. One row per journal LINE (a single posting
-- to a single account). A journal entry is the set of lines sharing a journal_id
-- and must always sum to zero (debits = credits). This is the double-entry
-- invariant the recon engine validates.

CREATE TABLE IF NOT EXISTS raw.gl_journal (
    journal_id           TEXT        NOT NULL,
    journal_line_id      INTEGER     NOT NULL,
    entity_id            INTEGER     NOT NULL REFERENCES raw.dim_entity(entity_id),
    business_date        DATE        NOT NULL,           -- the accounting date (period date)
    posting_date         DATE        NOT NULL,           -- when it actually hit the GL
    account_code         TEXT        NOT NULL,
    debit_usd            NUMERIC(18,2) NOT NULL DEFAULT 0,
    credit_usd           NUMERIC(18,2) NOT NULL DEFAULT 0,
    currency             CHAR(3)     NOT NULL,
    amount_currency      NUMERIC(18,2) NOT NULL,
    fx_rate              NUMERIC(18,8) NOT NULL,
    source_system        TEXT        NOT NULL CHECK (source_system IN ('AP','AR','INV','MANUAL','FX_REVAL')),
    source_doc_id        TEXT,                           -- FK back to the originating sub-ledger row
    description          TEXT,
    created_by           TEXT        NOT NULL,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (journal_id, journal_line_id),
    CHECK (debit_usd >= 0 AND credit_usd >= 0),
    CHECK (NOT (debit_usd > 0 AND credit_usd > 0))      -- a line is debit OR credit, not both
);

CREATE INDEX IF NOT EXISTS ix_gl_business_date  ON raw.gl_journal(business_date, entity_id, account_code);
CREATE INDEX IF NOT EXISTS ix_gl_posting_date   ON raw.gl_journal(posting_date, entity_id);
CREATE INDEX IF NOT EXISTS ix_gl_source         ON raw.gl_journal(source_system, source_doc_id);

COMMENT ON TABLE  raw.gl_journal IS 'General Ledger postings. One row per journal line. debit_usd + credit_usd per journal_id must net to zero.';
COMMENT ON COLUMN raw.gl_journal.business_date IS 'Accounting date - the period in which the transaction belongs.';
COMMENT ON COLUMN raw.gl_journal.posting_date  IS 'Operational date - when the line was actually written to the GL. Differs from business_date during cut-off / late postings.';
COMMENT ON COLUMN raw.gl_journal.source_system IS 'AP, AR, INV (sub-ledger feeds), MANUAL (human JE - SOX flag), FX_REVAL (period-end revaluation).';
