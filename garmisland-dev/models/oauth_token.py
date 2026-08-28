from odoo import models, fields

class OAuthToken(models.Model):
    _name = 'garm.oauth.token'
    _description = "Garm Island oauth Access Token"

    access_token = fields.Char(required=True)

    client_id = fields.Many2one(
        "garm.oauth.client",
        required=True
    )

    user_id = fields.Many2one(
        "res.users",
        required=True
    )

    revoked = fields.Boolean(default=False)
