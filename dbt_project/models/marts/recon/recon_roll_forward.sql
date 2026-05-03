/*
    recon_roll_forward
    ------------------
    Validates the fundamental ledger arithmetic:
        opening_balance + period_activity = closing_balance
    in BOTH the sub-ledger and the GL, independently.

    This catches silent restatements, missing opening balances after a
    backfill, or any other arithmetic break that wouldn't surface in
    the control-account check (which compares two systems day-by-day).
*/

with sl as (
    select
        entity_id,
        account_code,
        posting_date,
        running_balance_usd,
        lag(running_balance_usd) over (
            partition by entity_id, account_code
            order by posting_date
        )                                            as prior_balance_usd,
        daily_net_usd
    from {{ ref('int_subledger_trial_balance') }}
),

gl as (
    select
        entity_id,
        account_code,
        posting_date,
        running_balance_usd,
        lag(running_balance_usd) over (
            partition by entity_id, account_code
            order by posting_date
        )                                            as prior_balance_usd,
        daily_net_usd
    from {{ ref('int_gl_trial_balance') }}
),

unioned as (
    select 'SUBLEDGER'::text as ledger, * from sl
    union all
    select 'GL'::text         as ledger, * from gl
)

select
    ledger,
    entity_id,
    account_code,
    posting_date,
    coalesce(prior_balance_usd, 0)              as opening_balance_usd,
    daily_net_usd                               as activity_usd,
    running_balance_usd                         as closing_balance_usd,
    (running_balance_usd
        - coalesce(prior_balance_usd, 0)
        - daily_net_usd)::numeric(18,2)         as roll_forward_variance_usd,
    case
        when abs(running_balance_usd
                  - coalesce(prior_balance_usd, 0)
                  - daily_net_usd) <= 0.01
            then 'PASS'
        else 'FAIL'
    end as status
from unioned
