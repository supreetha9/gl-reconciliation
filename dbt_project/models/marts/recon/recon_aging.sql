/*
    recon_aging
    -----------
    Buckets each unmatched item from `recon_transaction_level` by age
    (current_date - first_seen_date). Drives the controller's daily
    triage view: "what breaks have been sitting for more than a week?"
*/

with breaks as (
    select *
    from {{ ref('recon_transaction_level') }}
    where status = 'BREAK'
),

aged as (
    select
        b.*,
        (current_date - coalesce(b.business_date, b.sl_posting_date, b.gl_posting_date)) as age_days
    from breaks b
)

select
    a.*,
    case
        when a.age_days <= 1                      then '0-1d'
        when a.age_days <= 7                      then '2-7d'
        when a.age_days <= 30                     then '8-30d'
        else '30+d'
    end as age_bucket,
    case
        when a.age_days > 30                      then 'CRITICAL'
        when a.age_days > 7                       then 'HIGH'
        when a.age_days > 1                       then 'MEDIUM'
        else 'LOW'
    end as triage_priority
from aged a
