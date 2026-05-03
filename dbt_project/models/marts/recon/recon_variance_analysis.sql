/*
    recon_variance_analysis
    -----------------------
    Slices the control-account variance by entity, account, and currency.
    Filters to only material variances (above per-account threshold from
    seeds/materiality.csv). This is the first thing the controller looks
    at every morning.
*/

with ctrl as (
    select * from {{ ref('recon_control_account') }}
)

select
    c.posting_date,
    c.entity_id,
    e.entity_code,
    e.functional_currency,
    c.account_code,
    a.account_name,
    a.account_type,
    c.sl_balance_usd,
    c.gl_balance_usd,
    c.variance_usd,
    abs(c.variance_usd) as abs_variance_usd,
    c.materiality_usd,
    c.severity,
    case
        when abs(c.variance_usd) >= c.materiality_usd then true
        else false
    end as is_material,
    c.status,
    rank() over (
        partition by c.posting_date
        order by abs(c.variance_usd) desc
    ) as variance_rank_in_day
from ctrl c
left join {{ ref('stg_dim_entity') }}  e on e.entity_id    = c.entity_id
left join {{ ref('stg_dim_account') }} a on a.account_code = c.account_code
where c.status <> 'PASS'
