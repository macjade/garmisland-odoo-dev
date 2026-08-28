from odoo import models, fields
from odoo.fields import Datetime
from dateutil.relativedelta import relativedelta

class OAuthCode(models.Model):
    _name = 'garm.oauth.code'
    _description = "Garm Island oauth Authorization Code"

    code = fields.Char(required=True)

    client_id = fields.Many2one(
        "garm.oauth.client",
        required=True
    )

    user_id = fields.Many2one(
        "res.users",
        required=True
    )

    expires_at = fields.Datetime(
        default=lambda self: Datetime.now() + relativedelta(seconds=(60 * 24 * 30))
    )

    used = fields.Boolean(default=False)