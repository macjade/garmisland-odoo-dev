from odoo import api, SUPERUSER_ID
import secrets
import logging

from . import models
from . import controllers

logger = logging.getLogger(__name__)

def _account_post_init_hook(env):

    logger.warning(f"Garm Island app installed successfully")
    payload = {
        'name': 'Garm Tokens',
        'client_id': secrets.token_urlsafe(32),
        'client_secret': secrets.token_urlsafe(64)
    }

    env['garm.oauth.client'].create(payload)

    payload['store_name'] = env.company.name
    payload['store_url']  = env['ir.config_parameter'].sudo().get_param('web.base.url')
    payload['website_name'] = env['website'].get_current_website().name
    payload['website_url']  = env['website'].get_current_website().get_base_url()

    logger.warning(f"Garm Island app installed: {payload}")
    
    logger.warning(f"Register Installation on Garm Island Backend")

