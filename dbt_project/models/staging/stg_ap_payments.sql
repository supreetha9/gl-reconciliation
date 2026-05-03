with src as (
    select * from {{ source('raw', 'ap_payments') }}
)

select
    payment_id,
    invoice_id,
    entity_id,
    payment_date,
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
