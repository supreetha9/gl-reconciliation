/*
    recon_suspense_monitor
    ----------------------
    The 9999 suspense account series should always net to zero --
    anything sitting in suspense is by definition unmapped and needs
    a controller to investigate. Even a single dollar in 9999 is a
    HIGH-severity exception.
*/

select
    entity_id,
    account_code,
    posting_date,
    daily_debits_usd,
    daily_credits_usd,
    running_balance_usd as suspense_balance_usd,
    case
        when running_balance_usd = 0 then 'PASS'
        else 'FAIL'
    end as status
from {{ ref('int_gl_trial_balance') }}
where account_code like '9%'
