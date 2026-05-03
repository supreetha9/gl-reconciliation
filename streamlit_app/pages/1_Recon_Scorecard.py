"""Recon Scorecard — historical pass/fail/$ breakdown by check."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st
from lib.db import query_df
from lib.format import status_badge

st.set_page_config(page_title="Recon Scorecard", layout="wide")
st.title("Recon Scorecard")
st.caption("Pass/fail counts and break value across all reconciliation runs.")

# ---------------------------------------------------------------------------
# Load history
# ---------------------------------------------------------------------------

runs_df = query_df("""
    SELECT r.run_id, r.business_date, r.status,
           r.started_at, r.finished_at, r.triggered_by
    FROM audit.recon_runs r
    ORDER BY r.started_at DESC
    LIMIT 30
""")

if runs_df.empty:
    st.warning("No runs in the audit trail yet.")
    st.stop()

st.subheader("Run history")
st.dataframe(
    runs_df.assign(
        run_id_short=lambda d: d["run_id"].astype(str).str[:8] + "…",
    )[["run_id_short", "business_date", "status", "triggered_by",
       "started_at", "finished_at"]],
    hide_index=True,
    use_container_width=True,
)

# ---------------------------------------------------------------------------
# Per-check trend
# ---------------------------------------------------------------------------

checks_df = query_df("""
    SELECT cr.check_name,
           cr.status,
           cr.breaks_count,
           cr.breaks_value_usd,
           r.business_date,
           r.started_at
    FROM audit.recon_check_results cr
    JOIN audit.recon_runs r USING (run_id)
    WHERE r.started_at >= now() - interval '60 days'
    ORDER BY r.started_at, cr.check_name
""")

if checks_df.empty:
    st.info("No per-check results in the last 60 days.")
    st.stop()

st.markdown("---")

# Latest-run snapshot
latest_run_id = runs_df.iloc[0]["run_id"]
latest_checks = checks_df[checks_df["business_date"] == runs_df.iloc[0]["business_date"]]

st.subheader(f"Latest run: {runs_df.iloc[0]['business_date']}")
cols = st.columns(min(len(latest_checks), 4) or 1)
for i, row in enumerate(latest_checks.itertuples(index=False)):
    with cols[i % len(cols)]:
        st.markdown(f"**{row.check_name}**")
        st.markdown(status_badge(row.status), unsafe_allow_html=True)
        st.metric("Breaks", f"{int(row.breaks_count):,}")
        st.metric("Value (USD)", f"${float(row.breaks_value_usd):,.2f}")

# ---------------------------------------------------------------------------
# Breaks $ trend chart
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Break value over time")

trend_df = checks_df.copy()
trend_df["breaks_value_usd"] = trend_df["breaks_value_usd"].astype(float)

chart = (
    alt.Chart(trend_df)
    .mark_line(point=True)
    .encode(
        x=alt.X("business_date:T", title="Business date"),
        y=alt.Y("breaks_value_usd:Q", title="Breaks ($USD)", stack=None),
        color=alt.Color("check_name:N", title="Check"),
        tooltip=["business_date:T", "check_name:N", "status:N", "breaks_value_usd:Q"],
    )
    .properties(height=350)
    .interactive()
)
st.altair_chart(chart, use_container_width=True)

# Breaks count per status
st.subheader("Pass / warn / fail composition")
status_counts = (
    checks_df.groupby(["business_date", "status"])
    .size()
    .reset_index(name="count")
)
status_chart = (
    alt.Chart(status_counts)
    .mark_bar()
    .encode(
        x=alt.X("business_date:T", title="Business date"),
        y=alt.Y("count:Q", title="Number of checks"),
        color=alt.Color(
            "status:N",
            scale=alt.Scale(
                domain=["PASS", "WARN", "FAIL"],
                range=["#198754", "#FFC107", "#DC3545"],
            ),
        ),
        tooltip=["business_date:T", "status:N", "count:Q"],
    )
    .properties(height=300)
)
st.altair_chart(status_chart, use_container_width=True)


# Suppress import warning if pandas is not directly referenced.
_ = pd
