with src as (
    select * from {{ source('raw', 'dim_account') }}
)

select
    account_id,
    account_code,
    account_name,
    account_type,
    parent_account_code,
    is_control_account,
    subledger_source,
    effective_from,
    effective_to,
    ingested_at
from src
