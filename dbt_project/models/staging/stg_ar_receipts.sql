with src as (
    select * from {{ source('raw', 'ar_receipts') }}
)

select
    receipt_id,
    invoice_id,
    entity_id,
    receipt_date,
    posting_date,
    currency,
    amount_currency,
    amount_usd,
    fx_rate,
    cash_account_code,
    control_account_code,
    method,
    ingested_at
from src
