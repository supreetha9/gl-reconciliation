/*
    recon_manual_je_flag
    --------------------
    SOX red-flag check. Manual journal entries posted directly to a
    control account (AP/AR/Inventory) are an audit risk -- those
    accounts should only be touched by their respective sub-ledger
    feeds. Every flagged row gets surfaced in the auditor evidence
    pack and triggers a Slack alert.
*/

with manual_jes as (
    select
        gl.journal_id,
        gl.journal_line_id,
        gl.entity_id,
        gl.business_date,
        gl.posting_date,
        gl.account_code,
        gl.debit_usd,
        gl.credit_usd,
        (gl.debit_usd + gl.credit_usd) as amount_usd,
        gl.created_by,
        gl.description
    from {{ ref('stg_gl_journal') }} gl
    where gl.source_system = 'MANUAL'
)

select
    m.journal_id,
    m.journal_line_id,
    m.entity_id,
    m.business_date,
    m.posting_date,
    m.account_code,
    a.account_name,
    a.is_control_account,
    m.amount_usd,
    m.created_by,
    m.description,
    case
        when a.is_control_account then 'FAIL'
        else 'PASS'
    end as status
from manual_jes m
left join {{ ref('stg_dim_account') }} a on a.account_code = m.account_code
where a.is_control_account = true
