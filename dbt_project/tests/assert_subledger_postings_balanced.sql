/*
    Singular test: every sub-ledger document (source_doc_id) translated
    via int_subledger_postings must produce a balanced pair of lines.
    If this fails, the UNION ALL in int_subledger_postings is wrong.
*/

{{ assert_balanced(
       model      = ref('int_subledger_postings'),
       group_by   = ['source_system', 'source_doc_id'],
       debit_col  = 'debit_usd',
       credit_col = 'credit_usd',
       tolerance  = 0.01) }}
