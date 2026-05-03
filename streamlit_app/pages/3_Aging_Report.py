"""Aging Report — heatmap of break age by account.

Reads `recon_aging` and pivots into a (account_code, age_bucket)
heatmap with break value as the colour scale. Drives the controller's
daily triage queue.
"""

from __future__ import annotations

import altair as alt
import streamlit as st
from lib.db import query_df
from lib.format import money

st.set_page_config(page_title="Aging Report", layout="wide")
st.title("Aging Report")
st.caption("Break age by account heatmap. The HIGH and CRITICAL buckets are the day's triage queue.")

# ---------------------------------------------------------------------------
# Headline KPIs
# ---------------------------------------------------------------------------

agg = query_df("""
    SELECT triage_priority,
           count(*)                 AS breaks,
           sum(abs(amount_delta_usd)) AS value_usd
    FROM glrecon_marts.recon_aging
    GROUP BY triage_priority
""")

if agg.empty:
    st.info("No aged breaks. The recon engine has nothing to triage today.")
    st.stop()

priority_order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
agg = agg.set_index("triage_priority").reindex(priority_order).fillna(0).reset_index()

cols = st.columns(len(priority_order))
for i, prio in enumerate(priority_order):
    row = agg[agg["triage_priority"] == prio].iloc[0]
    cols[i].metric(prio, f"{int(row['breaks']):,}", money(row["value_usd"]))

st.markdown("---")

# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------

st.subheader("Break value by account and age bucket")

heat_df = query_df("""
    SELECT account_code,
           age_bucket,
           sum(abs(amount_delta_usd)) AS value_usd,
           count(*)                   AS breaks
    FROM glrecon_marts.recon_aging
    GROUP BY account_code, age_bucket
    HAVING sum(abs(amount_delta_usd)) > 0
""")

if heat_df.empty:
    st.info("No aged break value above zero.")
else:
    heat_df["value_usd"] = heat_df["value_usd"].astype(float)
    chart = (
        alt.Chart(heat_df)
        .mark_rect()
        .encode(
            x=alt.X(
                "age_bucket:O",
                sort=["0-1d", "2-7d", "8-30d", "30+d"],
                title="Age bucket",
            ),
            y=alt.Y("account_code:O", title="Account"),
            color=alt.Color(
                "value_usd:Q",
                title="Break value (USD)",
                scale=alt.Scale(scheme="reds"),
            ),
            tooltip=[
                "account_code:O",
                "age_bucket:O",
                alt.Tooltip("value_usd:Q", format=",.2f"),
                alt.Tooltip("breaks:Q", format=","),
            ],
        )
        .properties(height=420)
    )
    st.altair_chart(chart, use_container_width=True)

# ---------------------------------------------------------------------------
# Triage queue
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Triage queue (HIGH + CRITICAL)")

queue = query_df("""
    SELECT triage_priority, age_bucket, source_system, source_doc_id,
           account_code, entity_id, business_date,
           sl_amount_usd, gl_amount_usd, amount_delta_usd, break_class
    FROM glrecon_marts.recon_aging
    WHERE triage_priority IN ('HIGH', 'CRITICAL')
    ORDER BY abs(amount_delta_usd) DESC
    LIMIT 200
""")

if queue.empty:
    st.success("Nothing in the triage queue. Nice work.")
else:
    display = queue.copy()
    for c in ("sl_amount_usd", "gl_amount_usd", "amount_delta_usd"):
        display[c] = display[c].apply(lambda v: money(v) if v is not None else "—")
    st.dataframe(display, hide_index=True, use_container_width=True, height=500)
