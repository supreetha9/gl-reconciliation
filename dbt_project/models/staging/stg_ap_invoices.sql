with src as (
    select * from {{ source('raw', 'ap_invoices') }}
)

select
    invoice_id,
    vendor_id,
    entity_id,
    invoice_date,
    posting_date,
    due_date,
    currency,
    amount_currency,
    amount_usd,
    fx_rate,
    expense_account_code,
    control_account_code,
    status,
    description,
    ingested_at
from src
