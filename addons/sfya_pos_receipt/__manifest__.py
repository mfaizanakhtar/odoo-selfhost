{
    'name': 'SFYA POS Receipt',
    'version': '18.0.2.0.0',
    'summary': 'SFYA-branded receipt layout for Point of Sale',
    'category': 'Point of Sale',
    'author': 'SFYA Enterprises',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'account'],
    'assets': {
        'point_of_sale._assets_pos': [
            'sfya_pos_receipt/static/src/app/order_receipt_patch.js',
            'sfya_pos_receipt/static/src/app/order_receipt.xml',
            'sfya_pos_receipt/static/src/app/receipt_screen_patch.js',
            'sfya_pos_receipt/static/src/scss/receipt.scss',
            'sfya_pos_receipt/static/src/app/ticket_screen_patch.js',
            'sfya_pos_receipt/static/src/app/ticket_screen.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
