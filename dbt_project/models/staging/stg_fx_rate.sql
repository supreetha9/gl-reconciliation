with src as (
    select * from {{ source('raw', 'fx_rate') }}
)

select
    rate_date,
    from_currency,
    to_currency,
    rate,
    ingested_at
from src
