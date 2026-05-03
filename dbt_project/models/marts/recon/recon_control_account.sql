/*
    recon_control_account
    ---------------------
    THE core check. For each control account (AP=2000, AR=1200, INV=1300):
    sub-ledger ending balance == GL control-account balance, per
    (entity, posting_date), within the configured tolerance.

    A break here is the highest-impact recon failure; it means the
    sub-ledger and the GL disagree about the company's outstanding
    payables/receivables/inventory on a given day.
*/

with control_accounts as (
    select account_code
    from {{ ref('stg_dim_account') }}
    where is_control_account = true
),

sl as (
    select * from {{ ref('int_subledger_trial_balance') }}
    where account_code in (select account_code from control_accounts)
),

gl as (
    select * from {{ ref('int_gl_trial_balance') }}
    where account_code in (select account_code from control_accounts)
),

joined as (
    select
        coalesce(sl.entity_id, gl.entity_id)        as entity_id,
        coalesce(sl.account_code, gl.account_code)  as account_code,
        coalesce(sl.posting_date, gl.posting_date)  as posting_date,
        coalesce(sl.daily_net_usd, 0)               as sl_daily_net_usd,
        coalesce(gl.daily_net_usd, 0)               as gl_daily_net_usd,
        coalesce(sl.running_balance_usd, 0)         as sl_balance_usd,
        coalesce(gl.running_balance_usd, 0)         as gl_balance_usd
    from sl
    full outer join gl
      on sl.entity_id    = gl.entity_id
     and sl.account_code = gl.account_code
     and sl.posting_date = gl.posting_date
)

select
    j.entity_id,
    j.account_code,
    j.posting_date,
    j.sl_daily_net_usd,
    j.gl_daily_net_usd,
    j.sl_balance_usd,
    j.gl_balance_usd,
    (j.sl_balance_usd - j.gl_balance_usd)::numeric(18,2) as variance_usd,
    {{ coalesce_tolerance('amount_tolerance_usd') }}     as amount_tolerance_usd,
    coalesce(m.materiality_usd, m_default.materiality_usd) as materiality_usd,
    coalesce(m.severity, m_default.severity)               as severity,
    case
        when abs(j.sl_balance_usd - j.gl_balance_usd) <= {{ coalesce_tolerance('amount_tolerance_usd') }}
            then 'PASS'
        when abs(j.sl_balance_usd - j.gl_balance_usd) >= coalesce(m.materiality_usd, m_default.materiality_usd)
            then 'FAIL'
        else 'WARN'
    end as status
from joined j
{{ tolerance_for('j.account_code') }}
left join {{ ref('materiality') }} m         on m.account_code         = j.account_code
left join {{ ref('materiality') }} m_default on m_default.account_code = 'DEFAULT'
