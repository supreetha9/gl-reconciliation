/*
    Singular test: every BREAK in recon_transaction_level must have a
    non-UNKNOWN break_class. UNKNOWN means the categorization macro
    failed to recognize the break shape, which usually means the
    macro needs an update.
*/

select *
from {{ ref('recon_transaction_level') }}
where status = 'BREAK'
  and break_class = 'UNKNOWN'
