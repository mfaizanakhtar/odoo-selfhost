from . import models


def _post_init_create_drawing_account(env):
    """Create 'Owner\'s Drawing' account per company if missing."""
    for company in env['res.company'].search([]):
        if company.sfya_owner_drawing_account_id:
            continue
        existing = env['account.account'].search([
            ('company_ids', 'in', company.id),
            ('code', '=', '3100'),
        ], limit=1)
        if existing:
            company.sfya_owner_drawing_account_id = existing.id
            continue
        # Need a chart of accounts to be installed for the company
        if not env['account.account'].search_count([('company_ids', 'in', company.id)], limit=1):
            continue
        account = env['account.account'].create({
            'code': '3100',
            'name': "Owner's Drawing",
            'account_type': 'equity',
            'company_ids': [(6, 0, [company.id])],
        })
        company.sfya_owner_drawing_account_id = account.id

    for company in env['res.company'].search([]):
        if company.sfya_partner_transfer_journal_id:
            continue
        journals = env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', company.id),
        ])
        if not journals:
            continue
        # Standard CoA installs name this journal's code 'MISC'; prefer it
        # when present so behavior matches the previous auto-search, but
        # fall back to the first general journal for non-standard setups.
        journal = journals.filtered(lambda j: j.code == 'MISC')[:1] or journals[:1]
        company.sfya_partner_transfer_journal_id = journal.id
