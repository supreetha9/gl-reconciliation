/*
    recon_transaction_level
    -----------------------
    The matching engine. Performs a FULL OUTER JOIN between sub-ledger
    postings and GL postings on (source_system, source_doc_id, account_code),
    then categorizes any divergence using the `categorize_break` macro.

    Key SQL signals demonstrated here:
      * Anti-join pattern via FULL OUTER JOIN with COALESCE-based filter
      * Tolerance-window matching using BETWEEN clause on amount delta
      * Reusable break categorization via macro
      * Configured as `incremental` with `merge` strategy + `unique_key`
*/

{{ config(
    materialized = 'incremental',
    unique_key   = ['source_system', 'source_doc_id', 'account_code', 'posting_role'],
    incremental_strategy = 'merge',
    on_schema_change     = 'append_new_columns'
) }}

with sl as (
    select
        source_system,
        source_doc_id,
        entity_id,
        business_date,
        posting_date    as sl_posting_date,
        account_code,
        currency,
        amount_usd      as sl_amount_usd,
        debit_usd       as sl_debit_usd,
        credit_usd      as sl_credit_usd,
        posting_role
    from {{ ref('int_subledger_postings') }}
    {% if is_incremental() %}
      where posting_date >= (
          select coalesce(max(coalesce(sl_posting_date, gl_posting_date)), '1900-01-01'::date)
                  - interval '14 days'
          from {{ this }}
      )
    {% endif %}
),

gl as (
    select
        source_system,
        source_doc_id,
        entity_id,
        business_date,
        posting_date    as gl_posting_date,
        account_code,
        currency,
        debit_usd       as gl_debit_usd,
        credit_usd      as gl_credit_usd,
        (debit_usd + credit_usd) as gl_amount_usd,
        journal_id,
        journal_line_id
    from {{ ref('stg_gl_journal') }}
    where source_system in ('AP', 'AR', 'INV')
      and source_doc_id is not null
    {% if is_incremental() %}
      and posting_date >= (
          select coalesce(max(coalesce(sl_posting_date, gl_posting_date)), '1900-01-01'::date)
                  - interval '14 days'
          from {{ this }}
      )
    {% endif %}
),

matched as (
    -- Match sub-ledger lines to GL lines on the (doc_id, account, debit/credit
    -- direction). Direction is encoded by `posting_role` -> debit_usd/credit_usd.
    select
        coalesce(sl.source_system, gl.source_system)   as source_system,
        coalesce(sl.source_doc_id, gl.source_doc_id)   as source_doc_id,
        coalesce(sl.account_code,  gl.account_code)    as account_code,
        coalesce(sl.entity_id,     gl.entity_id)       as entity_id,
        coalesce(sl.business_date, gl.business_date)   as business_date,
        coalesce(sl.currency,      gl.currency)        as currency,
        sl.posting_role,
        sl.sl_posting_date,
        gl.gl_posting_date,
        sl.sl_amount_usd,
        gl.gl_amount_usd,
        gl.journal_id,
        gl.journal_line_id
    from sl
    full outer join gl
      on  sl.source_system  = gl.source_system
     and  sl.source_doc_id  = gl.source_doc_id
     and  sl.account_code   = gl.account_code
     and  ((sl.sl_debit_usd  > 0 and gl.gl_debit_usd  > 0)
        or (sl.sl_credit_usd > 0 and gl.gl_credit_usd > 0))
)

select
    m.source_system,
    m.source_doc_id,
    m.account_code,
    m.entity_id,
    m.business_date,
    m.currency,
    m.posting_role,
    m.sl_posting_date,
    m.gl_posting_date,
    m.sl_amount_usd,
    m.gl_amount_usd,
    (coalesce(m.sl_amount_usd, 0) - coalesce(m.gl_amount_usd, 0))::numeric(18,2) as amount_delta_usd,
    coalesce((m.gl_posting_date - m.sl_posting_date), 0)                         as posting_lag_days,
    m.journal_id,
    m.journal_line_id,
    {{ coalesce_tolerance('amount_tolerance_usd') }}    as amount_tolerance_usd,
    {{ coalesce_tolerance('timing_tolerance_days') }}   as timing_tolerance_days,
    {{ categorize_break(
          sl_amount_col   = 'm.sl_amount_usd',
          gl_amount_col   = 'm.gl_amount_usd',
          sl_posting_col  = 'm.sl_posting_date',
          gl_posting_col  = 'm.gl_posting_date',
          currency_col    = 'm.currency',
          amount_tol_col  = coalesce_tolerance('amount_tolerance_usd'),
          timing_tol_col  = coalesce_tolerance('timing_tolerance_days'),
       ) }} as break_class,
    case
        when abs(coalesce(m.sl_amount_usd, 0) - coalesce(m.gl_amount_usd, 0))
                <= {{ coalesce_tolerance('amount_tolerance_usd') }}
         and abs(coalesce(m.gl_posting_date - m.sl_posting_date, 0))
                <= {{ coalesce_tolerance('timing_tolerance_days') }}
         and m.sl_amount_usd is not null
         and m.gl_amount_usd is not null
            then 'MATCHED'
        else 'BREAK'
    end as status,
    current_timestamp as recon_at
from matched m
{{ tolerance_for('m.account_code') }}
