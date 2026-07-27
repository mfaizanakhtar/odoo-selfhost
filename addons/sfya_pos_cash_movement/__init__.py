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
        # Dedicated journal rather than reusing an existing general journal
        # (e.g. Misc Operations): that journal's move-name sequence is
        # whatever the company already uses it for, and partner-transfer
        # entries would inherit an unrelated naming pattern.
        existing = env['account.journal'].search([
            ('code', '=', 'PXFR'),
            ('company_id', '=', company.id),
        ], limit=1)
        if existing:
            company.sfya_partner_transfer_journal_id = existing.id
            continue
        if not env['account.account'].search_count([('company_ids', 'in', company.id)], limit=1):
            continue
        journal = env['account.journal'].create({
            'name': 'Partner Transfers',
            'code': 'PXFR',
            'type': 'general',
            'company_id': company.id,
        })
        company.sfya_partner_transfer_journal_id = journal.id

    for company in env['res.company'].search([]):
        if company.sfya_internal_transfer_account_id:
            continue
        existing = env['account.account'].search([
            ('company_ids', 'in', company.id),
            ('code', '=', '1994'),
        ], limit=1)
        if existing:
            company.sfya_internal_transfer_account_id = existing.id
            continue
        if not env['account.account'].search_count([('company_ids', 'in', company.id)], limit=1):
            continue
        account = env['account.account'].create({
            'code': '1994',
            'name': 'Internal Transfers Clearing',
            'account_type': 'asset_current',
            'company_ids': [(6, 0, [company.id])],
        })
        company.sfya_internal_transfer_account_id = account.id
