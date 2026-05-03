"""Break Detail — filterable view of every unmatched item.

Drives off the `recon_transaction_level` mart. Lets a controller
filter by source system, account, break class, and status; click a
row to see the full sub-ledger and GL postings side by side.
"""

from __future__ import annotations

import streamlit as st
from lib.db import query_df
from lib.format import money

st.set_page_config(page_title="Break Detail", layout="wide")
st.title("Break Detail")
st.caption("Every transaction-level break categorized and ranked by impact.")

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

f_col1, f_col2, f_col3, f_col4 = st.columns(4)

source_systems = query_df("""
    SELECT DISTINCT source_system FROM glrecon_marts.recon_transaction_level
    ORDER BY source_system
""")["source_system"].tolist()
selected_systems = f_col1.multiselect("Source system", source_systems, default=source_systems)

statuses = ["BREAK", "MATCHED"]
selected_status = f_col2.multiselect("Status", statuses, default=["BREAK"])

accounts = query_df("""
    SELECT DISTINCT account_code FROM glrecon_marts.recon_transaction_level
    ORDER BY account_code
""")["account_code"].tolist()
selected_accounts = f_col3.multiselect("Account", accounts, default=accounts)

break_classes = query_df("""
    SELECT DISTINCT break_class FROM glrecon_marts.recon_transaction_level
    WHERE break_class IS NOT NULL
    ORDER BY break_class
""")["break_class"].tolist()
selected_classes = f_col4.multiselect(
    "Break class", break_classes, default=break_classes
)

min_abs_delta = st.slider(
    "Minimum absolute USD delta",
    min_value=0.0, max_value=10_000.0, value=0.0, step=10.0,
)

# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

if not (selected_systems and selected_status and selected_accounts and selected_classes):
    st.warning("Select at least one option in each filter.")
    st.stop()

placeholders = {
    "min_abs_delta": min_abs_delta,
    "systems": tuple(selected_systems),
    "statuses": tuple(selected_status),
    "accounts": tuple(selected_accounts),
    "classes": tuple(selected_classes),
}

# Note: psycopg supports tuple expansion via `IN :tuple_param`.
df = query_df(
    """
    SELECT source_system, source_doc_id, account_code, entity_id,
           sl_posting_date, gl_posting_date, sl_amount_usd, gl_amount_usd,
           amount_delta_usd, posting_lag_days, break_class, status,
           journal_id
    FROM glrecon_marts.recon_transaction_level
    WHERE source_system IN :systems
      AND status        IN :statuses
      AND account_code  IN :accounts
      AND break_class   IN :classes
      AND abs(coalesce(amount_delta_usd, 0)) >= :min_abs_delta
    ORDER BY abs(coalesce(amount_delta_usd, 0)) DESC
    LIMIT 1000
    """,
    placeholders,
)

st.markdown("---")
st.subheader(f"{len(df):,} rows  (top 1000 by |delta|)")

# ---------------------------------------------------------------------------
# Summary tiles
# ---------------------------------------------------------------------------

if not df.empty:
    total_value = df["amount_delta_usd"].abs().sum()
    by_class = df.groupby("break_class").size().to_dict()
    cols = st.columns(min(len(by_class) + 1, 6) or 1)
    cols[0].metric("Total |Δ|", money(total_value))
    for i, (cls, count) in enumerate(sorted(by_class.items(), key=lambda x: -x[1]), 1):
        if i < len(cols):
            cols[i].metric(cls, f"{count:,}")

# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

if df.empty:
    st.info("No breaks match the current filters.")
else:
    display = df.copy()
    for c in ("sl_amount_usd", "gl_amount_usd", "amount_delta_usd"):
        display[c] = display[c].apply(lambda v: money(v) if v is not None else "—")
    st.dataframe(display, hide_index=True, use_container_width=True, height=500)

    # Drill-through.
    st.markdown("---")
    st.subheader("Drill-through")
    selected_doc = st.selectbox(
        "Pick a source_doc_id to see the sub-ledger row + matching GL lines",
        df["source_doc_id"].dropna().unique().tolist(),
    )
    if selected_doc:
        d_col1, d_col2 = st.columns(2)

        with d_col1:
            st.markdown("**Sub-ledger postings**")
            sl = query_df(
                """
                SELECT * FROM glrecon_intermediate.int_subledger_postings
                WHERE source_doc_id = :doc
                """,
                {"doc": selected_doc},
            )
            st.dataframe(sl, hide_index=True, use_container_width=True)

        with d_col2:
            st.markdown("**GL postings**")
            gl = query_df(
                """
                SELECT * FROM glrecon_staging.stg_gl_journal
                WHERE source_doc_id = :doc
                """,
                {"doc": selected_doc},
            )
            st.dataframe(gl, hide_index=True, use_container_width=True)
