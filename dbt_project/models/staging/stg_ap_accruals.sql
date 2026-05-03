with src as (
    select * from {{ source('raw', 'ap_accruals') }}
)

select
    accrual_id,
    entity_id,
    accrual_date,
    posting_date,
    reversal_date,
    currency,
    amount_currency,
    amount_usd,
    fx_rate,
    expense_account_code,
    control_account_code,
    description,
    ingested_at
from src
