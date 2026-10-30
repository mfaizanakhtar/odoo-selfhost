{
    'name': 'SFYA POS Customer History Price',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Reuse the latest customer unit price from completed sales',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'account'],
    'assets': {
        'point_of_sale._assets_pos': [
            'sfya_pos_customer_history_price/static/src/app/history_price_service.js',
            'sfya_pos_customer_history_price/static/src/app/pos_order_patch.js',
            'sfya_pos_customer_history_price/static/src/app/pos_store_patch.js',
            'sfya_pos_customer_history_price/static/src/app/payment_screen_patch.js',
        ],
    },
    'installable': True,
}
