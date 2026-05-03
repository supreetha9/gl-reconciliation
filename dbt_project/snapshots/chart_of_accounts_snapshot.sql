{# ----------------------------------------------------------------------
   chart_of_accounts_snapshot
   --------------------------
   SCD2 snapshot on the chart of accounts. In the real world, account
   hierarchies get reorganized (parent_account_code changes), control-
   account flags flip, and accounts get retired. Auditors expect to see
   the COA exactly as it was on any historical period close, so we
   capture point-in-time state with `strategy: check`.

   Updated by `dbt snapshot`; consumed by historical recon backfills.
---------------------------------------------------------------------- #}

{% snapshot chart_of_accounts_snapshot %}
    {{
        config(
          target_schema='snapshots',
          unique_key='account_code',
          strategy='check',
          check_cols=['account_name', 'account_type', 'parent_account_code',
                      'is_control_account', 'subledger_source'],
          invalidate_hard_deletes=True,
        )
    }}

    select
        account_code,
        account_name,
        account_type,
        parent_account_code,
        is_control_account,
        subledger_source
    from {{ source('raw', 'dim_account') }}

{% endsnapshot %}
