with src as (
    select * from {{ source('raw', 'dim_entity') }}
)

select
    entity_id,
    entity_code,
    entity_name,
    functional_currency,
    country,
    ingested_at
from src
