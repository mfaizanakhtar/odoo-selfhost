{
    'name': 'SFYA POS Expense Bridge',
    'version': '18.0.2.0.0',
    'summary': 'Mirror paid hr.expense as POS cash-out on the open session',
    'category': 'Point of Sale',
    'author': 'SFYA Enterprises',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'hr', 'hr_expense'],
    'data': [
        'views/hr_expense_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
