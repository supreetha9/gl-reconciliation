/*
    int_gl_trial_balance
    --------------------
    Symmetric to int_subledger_trial_balance, but computed from the GL
    feed instead of the sub-ledger. The control-account check downstream
    is just a JOIN between the two trial balances on
    (entity_id, account_code, posting_date) with a tolerance comparison.
*/

with daily as (
    select
        entity_id,
        account_code,
        posting_date,
        sum(debit_usd)               as daily_debits_usd,
        sum(credit_usd)              as daily_credits_usd,
        sum(credit_usd - debit_usd)  as daily_net_usd
    from {{ ref('stg_gl_journal') }}
    group by entity_id, account_code, posting_date
)

select
    entity_id,
    account_code,
    posting_date,
    daily_debits_usd,
    daily_credits_usd,
    daily_net_usd,
    sum(daily_net_usd) over (
        partition by entity_id, account_code
        order by posting_date
        rows between unbounded preceding and current row
    ) as running_balance_usd
from daily
