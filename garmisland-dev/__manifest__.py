# -*- coding: utf-8 -*-
{
    "name": "Garm Island Dev",
    "version": "18.0.1.0.0",
    "license": "LGPL-3",
    "author": "James Maduka",
    "website": "www.jamesmaduka.com",
    "category": "Inventory Sync",
    "summary": """Garm Island syncs products and orders across your retail channels. Keep your inventory aligned.""",
    "description": """
        <section class="oe_container">
            <div class="oe_row oe_spaced">
                <h2 class="oe_slogan">Garm Island</h2>
                <p class="oe_slogan">Sync products and orders across your retail channels.</p>
                <p>Keep inventory aligned and manage your channel connections from Odoo.</p>
            </div>
        </section>
    """,
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