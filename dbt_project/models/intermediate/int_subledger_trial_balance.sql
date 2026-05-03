/*
    int_subledger_trial_balance
    ---------------------------
    Daily trial balance computed from the sub-ledger feeds.
    For each (entity, account, posting_date):
      * `daily_net`     -- credit - debit on that day (sub-ledger convention)
      * `running_balance` -- cumulative net using a window function
      * `daily_credits`, `daily_debits`

    The running_balance window function is one of the SQL skill signals
    called out in the project plan.
*/

with daily as (
    select
        entity_id,
        account_code,
        posting_date,
        sum(debit_usd)               as daily_debits_usd,
        sum(credit_usd)              as daily_credits_usd,
        sum(credit_usd - debit_usd)  as daily_net_usd
    from {{ ref('int_subledger_postings') }}
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
