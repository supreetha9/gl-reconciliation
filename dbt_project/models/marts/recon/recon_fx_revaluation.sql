/*
    recon_fx_revaluation
    --------------------
    Validates the period-end FX translation. For each non-USD posting,
    recompute its USD value at the period-end FX rate and compare to
    what's actually in the GL. Differences represent uncaptured
    translation gain/loss that should have been booked to account 7900.
*/

with non_usd as (
    select
        gl.entity_id,
        gl.posting_date,
        gl.account_code,
        gl.currency,
        gl.amount_currency,
        gl.amount_currency * fx.rate                as recomputed_amount_usd,
        (gl.debit_usd + gl.credit_usd)              as actual_amount_usd,
        gl.fx_rate                                  as posted_fx_rate,
        fx.rate                                     as eod_fx_rate
    from {{ ref('stg_gl_journal') }} gl
    left join {{ ref('stg_fx_rate') }} fx
      on fx.from_currency = gl.currency
     and fx.to_currency   = 'USD'
     and fx.rate_date     = gl.posting_date
    where gl.currency <> 'USD'
)

select
    entity_id,
    posting_date,
    account_code,
    currency,
    amount_currency,
    posted_fx_rate,
    eod_fx_rate,
    actual_amount_usd,
    recomputed_amount_usd,
    (recomputed_amount_usd - actual_amount_usd)::numeric(18,2) as fx_variance_usd,
    case
        when abs(recomputed_amount_usd - actual_amount_usd) <= 0.05 then 'PASS'
        when abs(recomputed_amount_usd - actual_amount_usd) <= 5.00 then 'WARN'
        else 'FAIL'
    end as status
from non_usd
