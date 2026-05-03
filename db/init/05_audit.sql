-- SOX-style audit trail. Append-only. Captures the control evidence for
-- every recon run: inputs hash, dbt manifest hash, per-check outcomes,
-- and a pointer to the exported evidence pack.

CREATE TABLE IF NOT EXISTS audit.recon_runs (
    run_id              UUID         PRIMARY KEY,
    business_date       DATE         NOT NULL,
    triggered_by        TEXT         NOT NULL,           -- 'schedule', 'manual:<user>', 'backfill'
    started_at          TIMESTAMPTZ  NOT NULL,
    finished_at         TIMESTAMPTZ,
    status              TEXT         NOT NULL CHECK (status IN ('RUNNING','PASS','FAIL','WARN','ERROR')),
    git_commit_sha      TEXT,
    dbt_manifest_hash   TEXT,
    source_row_counts   JSONB        NOT NULL DEFAULT '{}'::jsonb,
    evidence_url        TEXT
);
CREATE INDEX IF NOT EXISTS ix_recon_runs_business_date ON audit.recon_runs(business_date DESC);

CREATE TABLE IF NOT EXISTS audit.recon_check_results (
    run_id              UUID         NOT NULL REFERENCES audit.recon_runs(run_id) ON DELETE CASCADE,
    check_name          TEXT         NOT NULL,
    status              TEXT         NOT NULL CHECK (status IN ('PASS','FAIL','WARN')),
    breaks_count        INTEGER      NOT NULL DEFAULT 0,
    breaks_value_usd    NUMERIC(18,2) NOT NULL DEFAULT 0,
    materiality_usd     NUMERIC(18,2),
    details             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, check_name)
);

COMMENT ON TABLE audit.recon_runs         IS 'Append-only log of every reconciliation execution. Auditor evidence.';
COMMENT ON TABLE audit.recon_check_results IS 'Per-check outcome for each run. Drives the Streamlit scorecard and the exported evidence pack.';
