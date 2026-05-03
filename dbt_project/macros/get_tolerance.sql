{# ----------------------------------------------------------------------
   get_tolerance(account_code_col)
   --------------------------------
   Returns a SQL fragment that resolves the tolerance triple
   (amount_tolerance_usd, timing_tolerance_days, fx_tolerance_pct) for
   any join key column. Falls back to the DEFAULT row if the account is
   not explicitly listed in `seeds/tolerance_rules.csv`.

   Usage:
       {{ get_tolerance_join('control_account_code') }}

   Emits:
       LEFT JOIN ... so the calling model can reference
       `tol.amount_tolerance_usd` etc.
---------------------------------------------------------------------- #}

{% macro get_tolerance_cte() %}
with tolerance_resolved as (
    select
        account_code,
        amount_tolerance_usd,
        timing_tolerance_days,
        fx_tolerance_pct
    from {{ ref('tolerance_rules') }}
),
tolerance_default as (
    select
        amount_tolerance_usd,
        timing_tolerance_days,
        fx_tolerance_pct
    from {{ ref('tolerance_rules') }}
    where account_code = 'DEFAULT'
)
{% endmacro %}


{% macro tolerance_for(account_code_col, alias='tol') %}
left join {{ ref('tolerance_rules') }} as {{ alias }}_specific
    on {{ alias }}_specific.account_code = {{ account_code_col }}
left join {{ ref('tolerance_rules') }} as {{ alias }}_default
    on {{ alias }}_default.account_code = 'DEFAULT'
{% endmacro %}


{% macro coalesce_tolerance(field, alias='tol') %}
coalesce({{ alias }}_specific.{{ field }}, {{ alias }}_default.{{ field }})
{% endmacro %}
