/*
    Singular test: every journal_id in the GL should net to zero in USD
    (debits == credits) -- the most fundamental ledger invariant.

    The break injector intentionally perturbs single-line USD amounts
    (the AMOUNT_MISMATCH and FX_ROUNDING break classes), producing a
    small number of unbalanced journals BY DESIGN. So this test is
    configured as:
        warn_if  > 0     -> any unbalanced journal raises a warning
        error_if > 1500  -> a spike beyond known injection rates fails
*/

{{ config(severity='warn', warn_if='>0', error_if='>1500') }}

{{ assert_balanced(
       model      = ref('stg_gl_journal'),
       group_by   = ['journal_id'],
       debit_col  = 'debit_usd',
       credit_col = 'credit_usd',
       tolerance  = 0.01) }}
