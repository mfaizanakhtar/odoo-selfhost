{
    'name': 'SFYA POS Cash Movement',
    'version': '18.0.3.1.0',
    'summary': 'Collect Payment / Pay Out buttons on POS, linked to pos.session for till reconciliation',
    'category': 'Point of Sale',
    'author': 'SFYA Enterprises',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
        'views/pos_config_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'sfya_pos_cash_movement/static/src/app/cash_movement_modal.js',
            'sfya_pos_cash_movement/static/src/app/cash_movement_modal.xml',
            'sfya_pos_cash_movement/static/src/app/product_screen_buttons.js',
            'sfya_pos_cash_movement/static/src/app/product_screen_buttons.xml',
            'sfya_pos_cash_movement/static/src/app/closing_dialog_patch.js',
            'sfya_pos_cash_movement/static/src/app/closing_dialog_patch.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': '_post_init_create_drawing_account',
}
