# Run AFTER the -u upgrade (which runs the migration). Read-only assertions.
Exp = env['hr.expense']
pos_cash = Exp._sfya_pos_cash_journal()
missing = Exp.search_count([
    ('payment_mode', '=', 'company_account'),
    ('sfya_payment_source_journal_id', '=', False),
])
print("company_account expenses missing source journal:", missing)  # expect 0
sample = Exp.search([('payment_mode', '=', 'company_account')], limit=3)
for e in sample:
    print(e.id, e.name, "->", e.sfya_payment_source_journal_id.name,
          "== pos_cash?", e.sfya_payment_source_journal_id == pos_cash)
# no rollback: this is read-only
