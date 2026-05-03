"""Postgres bronze-layer loader.

Reads CSVs produced by ``run_pipeline`` (or in-memory DataFrames) and
truncate-loads them into the corresponding ``raw.*`` tables. Uses the
fast COPY protocol via psycopg for the wide tables.

Truncate-and-reload is the right pattern for a synthetic-data dev loop;
the production pipeline will use dbt incremental models for the real
upserts (Phase 2).
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from .config import Settings
from .logging_setup import get_logger

log = get_logger(__name__)


# Load order matters because of FK constraints.
LOAD_ORDER: list[str] = [
    "raw.dim_entity",
    "raw.dim_account",
    "raw.fx_rate",
    "raw.ap_invoices",
    "raw.ap_payments",
    "raw.ap_accruals",
    "raw.ar_invoices",
    "raw.ar_receipts",
    "raw.ar_credit_memos",
    "raw.inv_transactions",
    "raw.gl_journal",
]


def _table_columns(engine, qualified: str) -> list[str]:
    schema, table = qualified.split(".", 1)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :s AND table_name = :t
              AND column_default IS DISTINCT FROM 'now()'   -- skip ingested_at
              AND column_name <> 'ingested_at'
            ORDER BY ordinal_position
        """), {"s": schema, "t": table}).fetchall()
    return [r[0] for r in rows]


def _copy_dataframe(engine, qualified: str, df: pd.DataFrame) -> int:
    cols = _table_columns(engine, qualified)
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return 0
    buf = StringIO()
    df[cols].to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur, cur.copy(
            f"COPY {qualified} ({', '.join(cols)}) FROM STDIN WITH (FORMAT CSV, NULL '')"
        ) as copy:
            copy.write(buf.read())
        raw_conn.commit()
    finally:
        raw_conn.close()
    return len(df)


def load_dataframes(settings: Settings, tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    engine = create_engine(settings.postgres_dsn, future=True)
    loaded: dict[str, int] = {}

    with engine.begin() as conn:
        # Truncate child-first (reverse load order) to honour FKs.
        for tbl in reversed(LOAD_ORDER):
            conn.execute(text(f"TRUNCATE {tbl} CASCADE"))
        log.info("loader.truncated", tables=LOAD_ORDER)

    for tbl in LOAD_ORDER:
        if tbl not in tables:
            log.warning("loader.skip_missing_table", table=tbl)
            continue
        n = _copy_dataframe(engine, tbl, tables[tbl])
        loaded[tbl] = n
        log.info("loader.loaded", table=tbl, rows=n)

    return loaded


def load_csv_dir(settings: Settings, csv_dir: Path) -> dict[str, int]:
    tables: dict[str, pd.DataFrame] = {}
    for tbl in LOAD_ORDER:
        path = csv_dir / f"{tbl.replace('.', '__')}.csv"
        if path.exists():
            tables[tbl] = pd.read_csv(path)
        else:
            log.warning("loader.csv_not_found", path=str(path))
    return load_dataframes(settings, tables)
