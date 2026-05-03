with src as (
    select * from {{ source('raw', 'ar_credit_memos') }}
)

select
    memo_id,
    invoice_id,
    entity_id,
    memo_date,
    posting_date,
    currency,
    amount_currency,
    amount_usd,
    fx_rate,
    reason,
    revenue_account_code,
    control_account_code,
    ingested_at
from src
