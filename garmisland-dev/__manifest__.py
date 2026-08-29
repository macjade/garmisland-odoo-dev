# -*- coding: utf-8 -*-
{
    "name": "Garm Island Dev",
    "version": "18.0.1.0.0",
    "license": "LGPL-3",
    "author": "James Maduka",
    "website": "www.jamesmaduka.com",
    "category": "Inventory Sync",
    "summary": """Garm Island syncs products and orders across your retail channels. Keep your inventory aligned.""",
    "description": """Garm Island syncs products and orders across your retail channels. Keep your inventory aligned.""",
    "images": ["static/description/icon.png"],
    'depends': ['base', 'web', 'product', 'sale_management', 'sale_stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/garmisland_authorization_views.xml'
    ],
    "application": True,
    "installable": True,
    "auto_install": True,
    "post_init_hook": '_account_post_init_hook',
}