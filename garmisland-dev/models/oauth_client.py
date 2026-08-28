from odoo import models, fields
import secrets

class OAuthClient(models.Model):
    _name = 'garm.oauth.client'
    _description = "Garm Island oauth with backend"

    name = fields.Char(required=True)

    client_id = fields.Char(
        default=lambda self: secrets.token_urlsafe(32)
    )

    client_secret = fields.Char(
        default=lambda self: secrets.token_urlsafe(64)
    )

    active = fields.Boolean(default=True)