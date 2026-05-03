/*
    int_subledger_postings
    ----------------------
    Translates every sub-ledger row (AP, AR, Inventory) into the same
    GL-line shape so the recon engine can compare apples to apples.

    Every business event produces TWO rows here -- one debit, one credit
    -- mirroring the double-entry posting that the source system would
    have generated on the way to the GL. This is what makes the
    transaction-level matching engine in `recon_transaction_level`
    possible: it can anti-join sub-ledger rows directly against
    `stg_gl_journal` rows on `(source_system, source_doc_id, account_code)`.

    Posting direction reference:
      AP invoice  ->  Dr expense, Cr 2000 (AP control)
      AP payment  ->  Dr 2000,    Cr cash
      AR invoice  ->  Dr 1200,    Cr revenue
      AR receipt  ->  Dr cash,    Cr 1200
      INV RECEIPT ->  Dr 1300,    Cr 2000 (GR/IR)
      INV COGS    ->  Dr 5000,    Cr 1300
      INV ADJ     ->  Dr/Cr 1300, Cr/Dr 6900 (sign-dependent)
*/

with ap_invoice_lines as (
    select
        'AP'::text                              as source_system,
        invoice_id                              as source_doc_id,
        entity_id,
        invoice_date                            as business_date,
        posting_date,
        currency,
        amount_currency,
        amount_usd,
        fx_rate,
        expense_account_code                    as account_code,
        amount_usd                              as debit_usd,
        0::numeric(18,2)                        as credit_usd,
        'AP_INVOICE_EXPENSE'                    as posting_role
    from {{ ref('stg_ap_invoices') }}
    union all
    select
        'AP', invoice_id, entity_id, invoice_date, posting_date,
        currency, amount_currency, amount_usd, fx_rate,
        control_account_code, 0::numeric(18,2), amount_usd,
        'AP_INVOICE_CONTROL'
    from {{ ref('stg_ap_invoices') }}
),

ap_payment_lines as (
    select
        'AP', payment_id, entity_id, payment_date, posting_date,
        currency, amount_currency, amount_usd, fx_rate,
        control_account_code, amount_usd, 0::numeric(18,2),
        'AP_PAYMENT_CONTROL'
    from {{ ref('stg_ap_payments') }}
    union all
    select
        'AP', payment_id, entity_id, payment_date, posting_date,
        currency, amount_currency, amount_usd, fx_rate,
        cash_account_code, 0::numeric(18,2), amount_usd,
        'AP_PAYMENT_CASH'
    from {{ ref('stg_ap_payments') }}
),

ar_invoice_lines as (
    select
        'AR', invoice_id, entity_id, invoice_date, posting_date,
        currency, amount_currency, amount_usd, fx_rate,
        control_account_code, amount_usd, 0::numeric(18,2),
        'AR_INVOICE_CONTROL'
    from {{ ref('stg_ar_invoices') }}
    union all
    select
        'AR', invoice_id, entity_id, invoice_date, posting_date,
        currency, amount_currency, amount_usd, fx_rate,
        revenue_account_code, 0::numeric(18,2), amount_usd,
        'AR_INVOICE_REVENUE'
    from {{ ref('stg_ar_invoices') }}
),

ar_receipt_lines as (
    select
        'AR', receipt_id, entity_id, receipt_date, posting_date,
        currency, amount_currency, amount_usd, fx_rate,
        cash_account_code, amount_usd, 0::numeric(18,2),
        'AR_RECEIPT_CASH'
    from {{ ref('stg_ar_receipts') }}
    union all
    select
        'AR', receipt_id, entity_id, receipt_date, posting_date,
        currency, amount_currency, amount_usd, fx_rate,
        control_account_code, 0::numeric(18,2), amount_usd,
        'AR_RECEIPT_CONTROL'
    from {{ ref('stg_ar_receipts') }}
),

inv_resolved as (
    -- Resolve the (debit_account, credit_account) per inventory txn first;
    -- the UNION below then just emits a debit line + credit line for each.
    select
        txn_id,
        entity_id,
        txn_date,
        posting_date,
        txn_type,
        abs(amount_usd) as amount_abs_usd,
        case
            when txn_type = 'RECEIPT'                        then inventory_account_code  -- Dr 1300
            when txn_type = 'COGS'                           then inventory_account_code  -- Dr 5000 (COGS)
            when txn_type = 'ADJUSTMENT' and amount_usd >= 0 then inventory_account_code  -- Dr 1300
            else                                                  offset_account_code     -- Dr 6900 (ADJ neg)
        end as debit_account_code,
        case
            when txn_type = 'RECEIPT'                        then offset_account_code     -- Cr 2000 (AP)
            when txn_type = 'COGS'                           then offset_account_code     -- Cr 1300 (Inventory)
            when txn_type = 'ADJUSTMENT' and amount_usd >= 0 then offset_account_code     -- Cr 6900
            else                                                  inventory_account_code  -- Cr 1300 (ADJ neg)
        end as credit_account_code
    from {{ ref('stg_inv_transactions') }}
),

inv_lines as (
    select
        'INV'::text          as source_system,
        txn_id               as source_doc_id,
        entity_id,
        txn_date             as business_date,
        posting_date,
        'USD'::char(3)       as currency,
        amount_abs_usd       as amount_currency,
        amount_abs_usd       as amount_usd,
        1.0::numeric(18,8)   as fx_rate,
        debit_account_code   as account_code,
        amount_abs_usd       as debit_usd,
        0::numeric(18,2)     as credit_usd,
        ('INV_' || txn_type || '_DEBIT') as posting_role
    from inv_resolved

    union all

    select
        'INV', txn_id, entity_id, txn_date, posting_date,
        'USD', amount_abs_usd, amount_abs_usd, 1.0,
        credit_account_code, 0::numeric(18,2), amount_abs_usd,
        ('INV_' || txn_type || '_CREDIT')
    from inv_resolved
)

select * from ap_invoice_lines
union all select * from ap_payment_lines
union all select * from ar_invoice_lines
union all select * from ar_receipt_lines
union all select * from inv_lines
