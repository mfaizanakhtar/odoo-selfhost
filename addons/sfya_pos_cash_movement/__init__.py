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
