"""Recon Cockpit — landing page.

Shows the headline KPIs from the most recent reconciliation run plus
a quick navigation to the four detail pages.
"""

from __future__ import annotations

import streamlit as st
from lib import get_engine
from lib.format import money, status_badge
from sqlalchemy import text

st.set_page_config(
    page_title="GL Reconciliation Cockpit",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("GL Reconciliation Cockpit")
st.caption("Daily reconciliation of AP, AR, and Inventory sub-ledgers vs the General Ledger.")

# ---------------------------------------------------------------------------
# Latest run header
# ---------------------------------------------------------------------------

engine = get_engine()
with engine.connect() as conn:
    latest = conn.execute(text("""
        SELECT run_id, business_date, status, started_at, finished_at,
               triggered_by, source_row_counts
        FROM audit.recon_runs
        ORDER BY started_at DESC
        LIMIT 1
    """)).mappings().first()

if latest is None:
    st.warning(
        "No recon runs found yet. Trigger one with `make recon-run` "
        "or via the Dagster UI (`make dagster`)."
    )
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Business date", str(latest["business_date"]))
col2.markdown("**Status**")
col2.markdown(status_badge(latest["status"]), unsafe_allow_html=True)
col3.metric("Triggered by", latest["triggered_by"])
col4.metric("Run ID", str(latest["run_id"])[:8] + "…")

st.markdown("---")

# ---------------------------------------------------------------------------
# Per-check scorecard preview
# ---------------------------------------------------------------------------

with engine.connect() as conn:
    checks = conn.execute(text("""
        SELECT check_name, status, breaks_count, breaks_value_usd, materiality_usd
        FROM audit.recon_check_results
        WHERE run_id = :r
        ORDER BY check_name
    """), {"r": latest["run_id"]}).mappings().all()

st.subheader("Per-check scorecard")

if not checks:
    st.info("No per-check results recorded for this run yet.")
else:
    cols = st.columns(min(len(checks), 4))
    for i, c in enumerate(checks[:4]):
        with cols[i % 4]:
            st.markdown(f"**{c['check_name']}**")
            st.markdown(status_badge(c["status"]), unsafe_allow_html=True)
            st.metric("Breaks", f"{int(c['breaks_count']):,}")
            st.metric("Value", money(c["breaks_value_usd"]))

    st.markdown("Full table:")
    import pandas as pd
    df = pd.DataFrame(checks)
    df["breaks_value_usd"] = df["breaks_value_usd"].apply(money)
    df["materiality_usd"] = df["materiality_usd"].apply(money)
    st.dataframe(df, hide_index=True, use_container_width=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# Source row counts
# ---------------------------------------------------------------------------

st.subheader("Source row counts")
counts = latest.get("source_row_counts") or {}
if counts:
    import pandas as pd
    counts_df = pd.DataFrame(
        sorted(counts.items()), columns=["Table", "Rows"]
    )
    st.dataframe(counts_df, hide_index=True, use_container_width=True)
else:
    st.caption("No row counts recorded.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Navigation hint
# ---------------------------------------------------------------------------

st.subheader("Where to go from here")
st.markdown(
    """
- **Recon Scorecard** — pass/fail per check across all runs, with charts.
- **Break Detail** — filterable view of every unmatched item.
- **Aging Report** — heatmap of break age by account.
- **Auditor Evidence** — one-click Excel evidence-pack export for any run.
"""
)
