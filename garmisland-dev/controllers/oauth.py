from odoo import http
from odoo import fields
from odoo.http import request, Response
import secrets
from datetime import datetime, timedelta
import logging
import json

logger = logging.getLogger(__name__)

logger.info(">>>>>>>> OAUTH CONTROLLER FILE IS LOADED BY ODOO <<<<<<<<")

def authenticate():

    auth = request.httprequest.headers.get("Authorization")

    if not auth:
        return None

    token = auth.replace("Bearer ", "")

    return request.env[
        "garm.oauth.token"
    ].sudo().search([
        ("access_token", "=", token),
        ("revoked", "=", False)
    ], limit=1)

class GarmOAuthController(http.Controller):

    @http.route(
        '/garm/oauth/authorize',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
        website=True
    )

    def authorize(self, **kwargs):

        # client_id = kwargs.get("client_id", None)

        redirect_uri = kwargs.get("redirect_uri", None)

        state = kwargs.get("state", None)

        store_id = kwargs.get('store_id', None)

        scopes = kwargs.get("scopes", None)

        if not redirect_uri or not state or not store_id:
            return Response(
                "Missing required parameters: store_id, redirect_uri, and state are required.", 
                status=400
            )

        client = request.env[
            'garm.oauth.client'
        ].sudo().search([
            #('client_id', '=', client_id),
            ('active', '=', True)
        ], limit=1)

        if not client:
            return request.not_found()

        context = {
            'client': client,
            'redirect_uri': redirect_uri,
            'store_id': store_id,
            'state': state,
            'scopes': scopes.split(",") if scopes else scopes
        }

        return request.render(
            'garmisland.garm_authorize_page',
            context   
        )


    @http.route(
        '/garm/oauth/approve',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=True
    )
    def approve(self, **post):

        client_id = post.get("client_id")

        redirect_uri = post.get("redirect_uri")
        store_id = post.get("store_id")

        state = post.get("state")

        client = request.env[
            'garm.oauth.client'
        ].sudo().search([
            ('client_id', '=', client_id)
        ], limit=1)

        if not client:
            return request.not_found()

        code = secrets.token_urlsafe(32)

        request.env[
            'garm.oauth.code'
        ].sudo().create({

            'code': code,

            'client_id': client.id,

            'user_id': request.env.user.id,

            'expires_at': datetime.now() + timedelta(seconds=(60 * 24 * 30))

        })

        url = (
            redirect_uri
            + "?code="
            + code
            + "&client_id="
            + client.client_id
            + "&client_secret="
            + client.client_secret
            + "&store_id="
            + store_id
            + "&state="
            + state
        )

        return request.redirect(url, local=False)

    @http.route(
        '/garm/oauth/deny',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=True
    )
    def cancel(self, **post):

        redirect_uri = post.get("redirect_uri")

        url = redirect_uri

        return request.redirect(url, local=False)

    @http.route(
        '/garm/oauth/token',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def token(self, **post):

        client_id = post.get("client_id", None)
        client_secret = post.get("client_secret", None)
        code = post.get("code", None)

        if not client_id and request.httprequest.data:
            try:
                json_data = json.loads(request.httprequest.data.decode('utf-8'))
                client_id = json_data.get("client_id", None)
                client_secret = json_data.get("client_secret", None)
                code = json_data.get("code", None)
            except Exception:
                pass

        if not client_id or not client_secret or not code:
            return Response(
                json.dumps({
                    "error": "invalid_request",
                    "error_description": "Missing client_id, client_secret, or code."
                }),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

        client = request.env[
            "garm.oauth.client"
        ].sudo().search([
            ("client_id", "=", client_id),
            ("client_secret", "=", client_secret),
            ("active", "=", True)
        ], limit=1)

        if not client:
            return Response(
                json.dumps({
                    "error": "invalid_client",
                    "error_description": "Missing or inactive client."
                }),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )

        auth_code = request.env[
            "garm.oauth.code"
        ].sudo().search([
            ("code", "=", code),
            ("client_id", "=", client.id),
            ("used", "=", False)
        ], limit=1)

        if not auth_code:
            return Response(
                json.dumps({
                    "error": "invalid_grant",
                    "error_description": "Invalid authorization code."
                }),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )

        if auth_code.expires_at < fields.Datetime.now():
            return Response(
                json.dumps({
                    "error": "expired_code",
                    "error_description": "Authorization code has expired."
                }),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )

        auth_code.used = True

        access_token = secrets.token_urlsafe(64)

        request.env[
            "garm.oauth.token"
        ].sudo().create({

            "client_id": client.id,

            "user_id": auth_code.user_id.id,

            "access_token": access_token
        })


        context = {
            'access_token': access_token,
            'token_type': "Bearer"
        }
        return Response(
            json.dumps(context),
            status=200,
            headers=[('Content-Type', 'application/json')]
        )