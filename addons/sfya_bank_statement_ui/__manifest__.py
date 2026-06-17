{
    'name': 'SFYA Bank Statement UI',
    'version': '18.0.1.1.0',
    'summary': 'Re-enable manual bank statement creation + Journals top-level menu',
    'category': 'Accounting',
    'author': 'SFYA Enterprises',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'views/account_bank_statement_views.xml',
        'views/account_journal_menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
