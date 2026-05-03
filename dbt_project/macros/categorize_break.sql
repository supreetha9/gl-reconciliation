{# ----------------------------------------------------------------------
   categorize_break
   -----------------
   Maps the structural shape of a recon break to one of the named break
   classes the data generator injects. Used by `recon_transaction_level`
   and `recon_summary` to drive the controller's daily triage.

   Categories (must stay aligned with `data_generator/inject_breaks.py`):
     * MISSING_GL_POSTING -- sub-ledger row exists, no matching GL row
     * MISSING_SL_POSTING -- GL row exists with a source_doc_id but no SL row
     * AMOUNT_MISMATCH    -- both sides exist, USD delta > tolerance
     * TIMING_DIFF        -- both sides exist, posting-date delta > tolerance
     * FX_ROUNDING        -- amount delta < $0.10 and currency != USD
     * UNKNOWN
---------------------------------------------------------------------- #}

{% macro categorize_break(
        sl_amount_col='sl_amount_usd',
        gl_amount_col='gl_amount_usd',
        sl_posting_col='sl_posting_date',
        gl_posting_col='gl_posting_date',
        currency_col='currency',
        amount_tol_col='amount_tolerance_usd',
        timing_tol_col='timing_tolerance_days') %}
    case
        when {{ sl_amount_col }} is not null and {{ gl_amount_col }} is null
            then 'MISSING_GL_POSTING'
        when {{ sl_amount_col }} is null and {{ gl_amount_col }} is not null
            then 'MISSING_SL_POSTING'
        when abs(coalesce({{ sl_amount_col }},0) - coalesce({{ gl_amount_col }},0))
                > {{ amount_tol_col }}
            and abs(coalesce({{ sl_amount_col }},0) - coalesce({{ gl_amount_col }},0)) < 0.10
            and {{ currency_col }} <> 'USD'
            then 'FX_ROUNDING'
        when abs(coalesce({{ sl_amount_col }},0) - coalesce({{ gl_amount_col }},0))
                > {{ amount_tol_col }}
            then 'AMOUNT_MISMATCH'
        when abs(({{ gl_posting_col }} - {{ sl_posting_col }}))
                > {{ timing_tol_col }}
            then 'TIMING_DIFF'
        else 'UNKNOWN'
    end
{% endmacro %}
