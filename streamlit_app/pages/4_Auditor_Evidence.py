"""Auditor Evidence — pick a run, download the Excel pack."""

from __future__ import annotations

import uuid

import streamlit as st
from lib.db import get_engine, query_df

from recon_engine.evidence import build_evidence_pack, evidence_filename

st.set_page_config(page_title="Auditor Evidence", layout="wide")
st.title("Auditor Evidence")
st.caption(
    "Pick a reconciliation run and export the SOX evidence pack: a 6-sheet "
    "Excel workbook capturing the run, per-check results, top breaks, "
    "manual-JE flags, and a controller sign-off block."
)

# ---------------------------------------------------------------------------
# Run picker
# ---------------------------------------------------------------------------

runs = query_df("""
    SELECT run_id, business_date, status, started_at, finished_at, triggered_by
    FROM audit.recon_runs
    ORDER BY started_at DESC
    LIMIT 50
""")

if runs.empty:
    st.warning("No runs available yet. Trigger one with `make recon-run`.")
    st.stop()

runs["label"] = runs.apply(
    lambda r: f"{r['business_date']}  •  {r['status']}  •  {str(r['run_id'])[:8]}…  ({r['triggered_by']})",
    axis=1,
)
choice = st.selectbox("Run", runs["label"].tolist(), index=0)
selected = runs.iloc[runs["label"].tolist().index(choice)]

# ---------------------------------------------------------------------------
# Run details
# ---------------------------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)
c1.metric("Business date", str(selected["business_date"]))
c2.metric("Status", selected["status"])
c3.metric("Started", str(selected["started_at"]))
c4.metric("Finished", str(selected["finished_at"]))

st.markdown("---")

# ---------------------------------------------------------------------------
# Per-check preview
# ---------------------------------------------------------------------------

st.subheader("Per-check results (preview)")
checks = query_df(
    """
    SELECT check_name, status, breaks_count, breaks_value_usd, materiality_usd
    FROM audit.recon_check_results WHERE run_id = :r
    ORDER BY check_name
    """,
    {"r": selected["run_id"]},
)
st.dataframe(checks, hide_index=True, use_container_width=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# Build + download
# ---------------------------------------------------------------------------

st.subheader("Export")
top_n = st.slider("Top N breaks per sheet", min_value=20, max_value=500, value=100, step=20)

if st.button("Build evidence pack", type="primary"):
    with st.spinner("Assembling workbook…"):
        engine = get_engine()
        run_id = uuid.UUID(str(selected["run_id"]))
        data = build_evidence_pack(engine, run_id=run_id, top_n_breaks=top_n)
    fname = evidence_filename(selected["business_date"], run_id)
    st.success(f"Pack ready ({len(data) / 1024:.1f} KB).")
    st.download_button(
        label=f"Download {fname}",
        data=data,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.caption(
    "Auditors typically request this pack during quarterly walkthroughs. "
    "Sheet 6 (Sign-Off) is intentionally blank — fill it in, attach the "
    "exported file to the audit ticket, and you're done."
)
