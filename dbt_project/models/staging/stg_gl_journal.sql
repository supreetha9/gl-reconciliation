/*
    stg_gl_journal
    --------------
    Staging for the General Ledger.

    Why the dedup CTE?
    ------------------
    In production, the GL feed sometimes lands the same (journal_id,
    journal_line_id) more than once -- common with Kafka at-least-once
    delivery, or when a backfill replays a window. The canonical fix is
    to keep only the most recently ingested copy of each line.

    Pattern: ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ingested_at DESC),
    then filter to rn = 1. This is the dialect-portable equivalent of
    Snowflake/BigQuery's `QUALIFY` clause.
*/

with src as (
    select * from {{ source('raw', 'gl_journal') }}
),

ranked as (
    select
        journal_id,
        journal_line_id,
        entity_id,
        business_date,
        posting_date,
        account_code,
        debit_usd,
        credit_usd,
        currency,
        amount_currency,
        fx_rate,
        source_system,
        source_doc_id,
        description,
        created_by,
        ingested_at,
        row_number() over (
            partition by journal_id, journal_line_id
            order by ingested_at desc
        ) as rn
    from src
)

select
    journal_id,
    journal_line_id,
    entity_id,
    business_date,
    posting_date,
    account_code,
    debit_usd,
    credit_usd,
    (debit_usd - credit_usd)::numeric(18,2) as net_amount_usd,
    currency,
    amount_currency,
    fx_rate,
    source_system,
    source_doc_id,
    description,
    created_by,
    ingested_at
from ranked
where rn = 1
