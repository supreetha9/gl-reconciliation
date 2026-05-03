"""Intentional break injection.

Perturbs the (otherwise tidy) GL feed so the recon engine has realistic
exceptions to find. Five break classes, controlled by ``BreakRates`` in
the settings:

  * timing_diff           - sub-ledger T, GL T+1 (the most common break)
  * amount_mismatch       - small dollar delta between sub-ledger and GL
  * missing_gl_posting    - sub-ledger entry never reaches the GL
  * unauthorized_manual_je - manual JE retroactively flips to hit a control account
  * fx_rounding           - tiny noise on USD-translated amounts for non-USD rows

The injector is *idempotent given the same RNG state* and returns
``(perturbed_gl_df, breaks_log_df)`` so the test suite can assert on
exactly which rows were perturbed and which class of break was applied.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from .config import Settings
from .reference import AP_CONTROL, AR_CONTROL, INV_CONTROL

_CONTROL_ACCOUNTS = {AP_CONTROL, AR_CONTROL, INV_CONTROL}


def inject_breaks(
    settings: Settings,
    rng: np.random.Generator,
    gl: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply break perturbations and return ``(perturbed_gl, breaks_log)``."""
    df = gl.copy()
    log: list[dict] = []
    rates = settings.breaks

    # Restrict perturbations to sub-ledger-sourced rows only. Manual JEs are
    # already a separate audit-risk category and shouldn't be double-counted.
    eligible = df["source_system"].isin(["AP", "AR", "INV"])
    eligible_idx = df.index[eligible].to_numpy()

    # ----- 1. Timing differences: shift posting_date forward 1-2 days --------
    n_timing = int(rates.timing_diff * len(eligible_idx))
    timing_pick = rng.choice(eligible_idx, size=n_timing, replace=False)
    shifts = rng.choice([1, 2], size=n_timing, p=[0.7, 0.3])
    for i, s in zip(timing_pick, shifts, strict=True):
        new_post = df.at[i, "posting_date"] + timedelta(days=int(s))
        df.at[i, "posting_date"] = new_post
        log.append({
            "journal_id": df.at[i, "journal_id"],
            "journal_line_id": int(df.at[i, "journal_line_id"]),
            "break_class": "timing_diff",
            "detail": f"posting_date shifted by +{s} day(s)",
        })

    # ----- 2. Amount mismatches: penny-level noise ----------------------------
    pool = np.setdiff1d(eligible_idx, timing_pick, assume_unique=False)
    n_amt = int(rates.amount_mismatch * len(pool))
    amt_pick = rng.choice(pool, size=n_amt, replace=False)
    deltas = np.round(rng.uniform(-0.50, 0.50, size=n_amt), 2)
    deltas[deltas == 0] = 0.01
    for i, delta in zip(amt_pick, deltas, strict=True):
        if df.at[i, "debit_usd"] > 0:
            df.at[i, "debit_usd"] = round(df.at[i, "debit_usd"] + float(delta), 2)
        else:
            df.at[i, "credit_usd"] = round(df.at[i, "credit_usd"] + float(delta), 2)
        log.append({
            "journal_id": df.at[i, "journal_id"],
            "journal_line_id": int(df.at[i, "journal_line_id"]),
            "break_class": "amount_mismatch",
            "detail": f"USD amount perturbed by {delta:+.2f}",
        })

    # ----- 3. Missing GL postings: drop entire journal entry from GL ----------
    pool = np.setdiff1d(pool, amt_pick, assume_unique=False)
    eligible_jids = df.loc[pool, "journal_id"].unique()
    n_missing = int(rates.missing_gl_posting * len(eligible_jids))
    missing_jids = rng.choice(eligible_jids, size=n_missing, replace=False)
    drop_mask = df["journal_id"].isin(missing_jids)
    for jid in missing_jids:
        log.append({
            "journal_id": jid,
            "journal_line_id": -1,
            "break_class": "missing_gl_posting",
            "detail": "entire journal entry dropped from GL feed",
        })
    df = df.loc[~drop_mask].reset_index(drop=True)

    # ----- 4. Unauthorized manual JE flag -------------------------------------
    # Re-tag a small fraction of MANUAL JEs to hit a control account. These are
    # the SOX red flags the recon engine surfaces for auditor review.
    manual_idx = df.index[df["source_system"] == "MANUAL"].to_numpy()
    n_unauth = int(rates.unauthorized_manual_je * len(manual_idx))
    if n_unauth > 0 and len(manual_idx) > 0:
        unauth_pick = rng.choice(manual_idx, size=n_unauth, replace=False)
        # MANUAL JEs come in pairs (debit + credit lines). Re-point the credit line
        # of the same journal_id to a control account.
        unauth_jids = df.loc[unauth_pick, "journal_id"].unique()
        for jid in unauth_jids:
            mask = (df["journal_id"] == jid) & (df["credit_usd"] > 0)
            if mask.any():
                df.loc[mask, "account_code"] = str(rng.choice(list(_CONTROL_ACCOUNTS)))
                log.append({
                    "journal_id": jid,
                    "journal_line_id": -1,
                    "break_class": "unauthorized_manual_je",
                    "detail": "manual JE credit line repointed to a control account",
                })

    # ----- 5. FX rounding noise on non-USD rows -------------------------------
    non_usd_idx = df.index[df["currency"] != "USD"].to_numpy()
    n_fx = int(rates.fx_rounding * len(non_usd_idx))
    if n_fx > 0:
        fx_pick = rng.choice(non_usd_idx, size=n_fx, replace=False)
        deltas = np.round(rng.uniform(-0.05, 0.05, size=n_fx), 2)
        for i, delta in zip(fx_pick, deltas, strict=True):
            if df.at[i, "debit_usd"] > 0:
                df.at[i, "debit_usd"] = round(df.at[i, "debit_usd"] + float(delta), 2)
            else:
                df.at[i, "credit_usd"] = round(df.at[i, "credit_usd"] + float(delta), 2)
            log.append({
                "journal_id": df.at[i, "journal_id"],
                "journal_line_id": int(df.at[i, "journal_line_id"]),
                "break_class": "fx_rounding",
                "detail": f"FX rounding noise {delta:+.2f}",
            })

    breaks_log = pd.DataFrame(log, columns=["journal_id", "journal_line_id", "break_class", "detail"])
    return df.reset_index(drop=True), breaks_log
