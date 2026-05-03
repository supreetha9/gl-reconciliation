with src as (
    select * from {{ source('raw', 'inv_transactions') }}
)

select
    txn_id,
    item_id,
    entity_id,
    txn_date,
    posting_date,
    txn_type,
    quantity,
    unit_cost_usd,
    amount_usd,
    inventory_account_code,
    offset_account_code,
    description,
    ingested_at
from src
