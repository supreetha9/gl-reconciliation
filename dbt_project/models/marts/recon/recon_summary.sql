/*
    recon_summary
    -------------
    The scorecard. One row per (run_date, check_name) summarizing pass/
    fail counts and total break value. This is what the Streamlit Recon
    Cockpit reads first; it's also what gets persisted to
    `audit.recon_check_results` for the SOX evidence pack.
*/

with control_account as (
    select
        'control_account'                           as check_name,
        max(posting_date)                           as as_of_date,
        sum(case when status = 'PASS' then 1 else 0 end) as pass_count,
        sum(case when status = 'WARN' then 1 else 0 end) as warn_count,
        sum(case when status = 'FAIL' then 1 else 0 end) as fail_count,
        sum(case when status <> 'PASS' then abs(variance_usd) else 0 end) as breaks_value_usd
    from {{ ref('recon_control_account') }}
),

txn_level as (
    select
        'transaction_level'                         as check_name,
        max(coalesce(business_date, '1900-01-01'::date)) as as_of_date,
        sum(case when status = 'MATCHED' then 1 else 0 end) as pass_count,
        0                                           as warn_count,
        sum(case when status = 'BREAK'   then 1 else 0 end) as fail_count,
        sum(case when status = 'BREAK'   then abs(amount_delta_usd) else 0 end) as breaks_value_usd
    from {{ ref('recon_transaction_level') }}
),

roll_fwd as (
    select
        'roll_forward'                              as check_name,
        max(posting_date)                           as as_of_date,
        sum(case when status = 'PASS' then 1 else 0 end) as pass_count,
        0                                           as warn_count,
        sum(case when status = 'FAIL' then 1 else 0 end) as fail_count,
        sum(case when status = 'FAIL' then abs(roll_forward_variance_usd) else 0 end) as breaks_value_usd
    from {{ ref('recon_roll_forward') }}
)

select * from control_account
union all
select * from txn_level
union all
select * from roll_fwd
