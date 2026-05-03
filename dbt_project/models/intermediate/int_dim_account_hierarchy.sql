/*
    int_dim_account_hierarchy
    -------------------------
    Walks the parent_account_code chain in the chart of accounts to
    arbitrary depth using a RECURSIVE CTE. Adds:
      * `level`        -- 0 for root accounts, 1 for direct children, etc.
      * `root_code`    -- the topmost ancestor (handy for rollup pivots)
      * `path`         -- '/'-delimited ancestry, e.g. '1000/1100'

    This is the recursive-CTE skill signal called out in the plan.
*/

with recursive walked as (
    -- Anchor: roots have no parent.
    select
        account_code,
        account_name,
        account_type,
        parent_account_code,
        is_control_account,
        subledger_source,
        0                                       as level,
        account_code                            as root_code,
        account_code::text                      as path
    from {{ ref('stg_dim_account') }}
    where parent_account_code is null

    union all

    -- Recursive step: append children of the previous level.
    select
        child.account_code,
        child.account_name,
        child.account_type,
        child.parent_account_code,
        child.is_control_account,
        child.subledger_source,
        parent.level + 1                        as level,
        parent.root_code,
        parent.path || '/' || child.account_code as path
    from {{ ref('stg_dim_account') }} as child
    inner join walked as parent
        on child.parent_account_code = parent.account_code
)

select * from walked
