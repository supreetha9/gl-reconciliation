{# ----------------------------------------------------------------------
   assert_balanced(model, group_by_cols, debit_col, credit_col, tolerance)
   -----------------------------------------------------------------------
   The DRY recon assertion macro called out as a "skill signal" in the
   plan. Returns a SELECT that yields ONE ROW PER UNBALANCED GROUP --
   meaning a singular dbt test that uses this macro will fail when any
   group's debits and credits diverge by more than `tolerance`.

   Used by 5+ singular tests under `tests/`:
     * assert_gl_journal_balanced.sql
     * assert_subledger_ties_to_gl.sql
     * assert_recon_summary_internally_consistent.sql
     * ...

   Example (singular test):
       {{ assert_balanced(
              model       = ref('stg_gl_journal'),
              group_by    = ['journal_id'],
              debit_col   = 'debit_usd',
              credit_col  = 'credit_usd',
              tolerance   = 0.01) }}
---------------------------------------------------------------------- #}

{% macro assert_balanced(model, group_by, debit_col='debit_usd', credit_col='credit_usd', tolerance=0.01) %}
    select
        {{ group_by | join(', ') }},
        sum({{ debit_col }})  as total_debit,
        sum({{ credit_col }}) as total_credit,
        sum({{ debit_col }}) - sum({{ credit_col }}) as variance_usd
    from {{ model }}
    group by {{ group_by | join(', ') }}
    having abs(sum({{ debit_col }}) - sum({{ credit_col }})) > {{ tolerance }}
{% endmacro %}
