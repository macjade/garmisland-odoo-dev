from odoo import http
from odoo.http import request, Response
from datetime import datetime, timedelta
import logging
import json
import math
import base64
from urllib.parse import parse_qsl
from odoo.tools import html2plaintext
from .oauth import authenticate

logger = logging.getLogger(__name__)

logger.info(">>>>>>>> ORDER CONTROLLER FILE IS LOADED BY ODOO <<<<<<<<")

class GarmOrderController(http.Controller):

    def normalizeOrder(self, order):
        result = {}
        for key, val in order.items():
            if isinstance(val, tuple):
                result[key] = list(val)
            elif isinstance(val, list):
                result[key] = val
            else:
                try:
                    json.dumps(val)
                    result[key] = val
                except TypeError:
                    result[key] = str(val)

        return result

    def normalizeOrderLine(self, order_line):
        result = {}
        for key, val in order_line.items():
            if isinstance(val, tuple):
                result[key] = list(val)
            elif isinstance(val, list):
                result[key] = val
            elif isinstance(val, dict):
                result[key] = self.normalizeOrder(val)
            else:
                try:
                    json.dumps(val)
                    result[key] = val
                except TypeError:
                    result[key] = str(val)

        return result

    def _parse_order_note(self, note):
        if not note:
            return {}

        note_value = html2plaintext(note).strip()
        try:
            parsed = json.loads(note_value)
            return parsed if isinstance(parsed, dict) else {'note': note_value}
        except (TypeError, ValueError):
            return {'note': note_value}

    def _format_order(self, order, lines=None):
        order_obj = self.normalizeOrder(order)
        order_obj['lines'] = lines or []
        partner_id = order_obj.get('partner_id')
        partner = request.env['res.partner'].sudo().browse(
            partner_id[0] if isinstance(partner_id, list) else partner_id
        ) if partner_id else request.env['res.partner']
        order_obj['customer'] = self._customer_data(partner)
        note_payload = self._parse_order_note(order_obj.get('note'))
        shipping_partner = self._partner_from_order_field(order_obj.get('partner_shipping_id'))
        billing_partner = self._partner_from_order_field(order_obj.get('partner_invoice_id'))
        order_obj['customer_shipping_address'] = self._address_data(shipping_partner) or note_payload.get('shipping_address') or note_payload.get('customer_shipping_address') or {}
        order_obj['customer_billing_address'] = self._address_data(billing_partner) or note_payload.get('billing_address') or note_payload.get('customer_billing_address') or {}
        order_obj['custom_customer'] = note_payload.get('custom_customer') or note_payload.get('customer') or {}
        order_obj['shipping_lines'] = note_payload.get('shipping_lines') or note_payload.get('shipping_line_details') or []
        order_obj['item_lines'] = note_payload.get('item_lines') or note_payload.get('line_items') or order_obj['lines']
        order_obj['custom_item_lines'] = note_payload.get('item_lines') or note_payload.get('line_items') or note_payload.get('custom_item_lines') or []
        order_obj['discount_code'] = note_payload.get('discount_code') or note_payload.get('coupon_code') or note_payload.get('promo_code') or note_payload.get('discount') or None
        order_obj['order_metadata'] = note_payload
        return order_obj

    def _customer_data(self, customer):
        if not customer or not customer.exists():
            return {}
        return {
            'id': customer.id,
            'name': customer.name,
            'email': customer.email,
            'phone': customer.phone,
            'mobile': customer.mobile,
            'company': customer.commercial_company_name,
            'street': customer.street,
            'street2': customer.street2,
            'city': customer.city,
            'zip': customer.zip,
            'state': customer.state_id.name,
            'state_id': customer.state_id.id,
            'country': customer.country_id.name,
            'country_id': customer.country_id.id,
        }

    def _partner_from_order_field(self, value):
        if not value:
            return request.env['res.partner']
        partner_id = value[0] if isinstance(value, list) else value
        return request.env['res.partner'].sudo().browse(partner_id)

    def _address_data(self, address):
        if not address or not address.exists():
            return {}
        return {
            'id': address.id,
            'name': address.name,
            'email': address.email,
            'phone': address.phone,
            'street': address.street,
            'street2': address.street2,
            'city': address.city,
            'zip': address.zip,
            'state': address.state_id.name,
            'state_id': address.state_id.id,
            'country': address.country_id.name,
            'country_id': address.country_id.id,
        }

    def _clean_dict(self, value):
        if not isinstance(value, dict):
            return {}

        cleaned = {}
        for key, val in value.items():
            if val is None:
                continue
            cleaned[key] = val
        return cleaned

    def _safe_json_value(self, value):
        if value is None:
            return None
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    def _resolve_address_partner(self, address_data, partner_type='delivery'):
        address_data = self._clean_dict(address_data)
        if not address_data:
            return None

        partner_model = request.env['res.partner'].sudo()

        if not address_data.get('name'):
            address_data['name'] = address_data.get('first_name', '') + ' ' + address_data.get('last_name', '')
            address_data['name'] = address_data['name'].strip() or 'Customer'

        existing_domain = [('name', '=', address_data.get('name'))]
        for field_name in ['street', 'street2', 'city', 'zip', 'phone', 'email']:
            if address_data.get(field_name):
                existing_domain.append((field_name, '=', address_data.get(field_name)))

        partner = partner_model.search(existing_domain, limit=1)

        if not partner:
            partner_vals = {
                'name': address_data.get('name', 'Customer'),
                'street': address_data.get('street', ''),
                'street2': address_data.get('street2', ''),
                'city': address_data.get('city', ''),
                'zip': address_data.get('zip', ''),
                'phone': address_data.get('phone', ''),
                'email': address_data.get('email', ''),
                'type': 'delivery' if partner_type == 'delivery' else 'invoice',
            }
            if address_data.get('country_id'):
                country_obj = request.env['res.country'].sudo().search([('name', '=', address_data.get('country_id'))], limit=1)
                if country_obj:
                    partner_vals['country_id'] = country_obj.id
            if address_data.get('state_id'):
                state_val = address_data.get('state_id')
                try:
                    state_id_int = int(state_val)
                    state_obj = request.env['res.country.state'].sudo().browse(state_id_int)
                    if state_obj.exists():
                        partner_vals['state_id'] = state_obj.id
                except (ValueError, TypeError):
                    state_obj = request.env['res.country.state'].sudo().search(
                        [('code', '=', str(state_val).upper())], limit=1
                    )
                    if state_obj:
                        partner_vals['state_id'] = state_obj.id
                    else:
                        state_obj = request.env['res.country.state'].sudo().search(
                            [('name', '=', str(state_val))], limit=1
                        )
                        if state_obj:
                            partner_vals['state_id'] = state_obj.id
            partner = partner_model.create(partner_vals)

        return partner

    def _extract_custom_order_payload(self, post):
        shipping_address = post.get('shipping_address') or post.get('customer_shipping_address') or post.get('shipping')
        shipping_address = self._normalize_address(shipping_address)
        billing_address = post.get('billing_address') or post.get('customer_billing_address') or post.get('billing')
        billing_address = self._normalize_address(billing_address)
        custom_item_lines = post.get('custom_item_lines') or post.get('custom_items') or post.get('item_lines') or post.get('line_items') or []
        shipping_lines = post.get('shipping_lines') or post.get('shipping_line_details') or []
        shipping_lines = self._normalize_shipping_lines(shipping_lines)
        custom_customer = post.get('custom_customer') or post.get('customer') or post.get('custom_customer_data') or {}
        custom_customer = self._normalize_custom_customer(custom_customer)
        order_metadata = post.get('order_metadata') or post.get('metadata') or post.get('custom_order_metadata') or {}
        discount_code = post.get('discount_code') or post.get('coupon_code') or post.get('promo_code') or post.get('discount') or None

        return {
            'shipping_address': shipping_address,
            'billing_address': billing_address,
            'custom_item_lines': custom_item_lines,
            'shipping_lines': shipping_lines,
            'custom_customer': custom_customer,
            'order_metadata': order_metadata,
            'discount_code': discount_code,
        }

    def _resolve_customer_partner(self, customer_data):
        customer_data = self._clean_dict(customer_data)
        if not customer_data:
            return None

        if not customer_data.get('name'):
            customer_data['name'] = (
                f"{customer_data.get('first_name', '')} {customer_data.get('last_name', '')}".strip()
                or 'Customer'
            )

        partner_model = request.env['res.partner'].sudo()
        domain = [('name', '=', customer_data.get('name'))]
        if customer_data.get('email'):
            domain.append(('email', '=', customer_data.get('email')))

        partner = partner_model.search(domain, limit=1)
        if not partner:
            partner_vals = {
                'name': customer_data.get('name', 'Customer'),
                'email': customer_data.get('email', ''),
                'phone': customer_data.get('phone', ''),
                'street': customer_data.get('street', ''),
                'street2': customer_data.get('street2', ''),
                'city': customer_data.get('city', ''),
                'zip': customer_data.get('zip', ''),
                'type': 'contact',
            }
            if customer_data.get('country_id'):
                country_obj = request.env['res.country'].sudo().search([('name', '=', customer_data.get('country_id'))], limit=1)
                if country_obj:
                    partner_vals['country_id'] = country_obj.id
            if customer_data.get('state_id'):
                state_val = customer_data.get('state_id')
                try:
                    state_id_int = int(state_val)
                    state_obj = request.env['res.country.state'].sudo().browse(state_id_int)
                    if state_obj.exists():
                        partner_vals['state_id'] = state_obj.id
                except (ValueError, TypeError):
                    state_obj = request.env['res.country.state'].sudo().search(
                        [('code', '=', str(state_val).upper())], limit=1
                    )
                    if state_obj:
                        partner_vals['state_id'] = state_obj.id
                    else:
                        state_obj = request.env['res.country.state'].sudo().search(
                            [('name', '=', str(state_val))], limit=1
                        )
                        if state_obj:
                            partner_vals['state_id'] = state_obj.id
            partner = partner_model.create(partner_vals)

        return partner

    def _normalize_address(self, address_data):
        if not isinstance(address_data, dict):
            return {}
        
        normalized = {
            'first_name': address_data.get('first_name') or '',
            'last_name': address_data.get('last_name') or '',
            'street': address_data.get('street') or address_data.get('address') or address_data.get('address_1') or '',
            'street2': address_data.get('street2') or address_data.get('address_2') or '',
            'city': address_data.get('city') or '',
            'zip': address_data.get('zip') or address_data.get('postcode') or address_data.get('postal_code') or '',
            'phone': address_data.get('phone') or address_data.get('telephone') or '',
            'email': address_data.get('email') or '',
            'state_id': address_data.get('state_id') or address_data.get('state') or '',
            'country_id': address_data.get('country_id') or address_data.get('country') or '',
        }
        
        for key in address_data.keys():
            if key not in normalized:
                normalized[key] = address_data[key]
        
        return normalized

    def _normalize_custom_customer(self, customer_data):
        if not isinstance(customer_data, dict):
            return {}
        
        normalized = {
            'first_name': customer_data.get('first_name') or '',
            'last_name': customer_data.get('last_name') or '',
            'email': customer_data.get('email') or '',
            'phone': customer_data.get('phone') or customer_data.get('telephone') or '',
            'company': customer_data.get('company') or customer_data.get('organization') or '',
            'street': customer_data.get('street') or customer_data.get('address') or customer_data.get('address_1') or '',
            'street2': customer_data.get('street2') or customer_data.get('address_2') or '',
            'city': customer_data.get('city') or '',
            'zip': customer_data.get('zip') or customer_data.get('postcode') or customer_data.get('postal_code') or '',
            'state_id': customer_data.get('state_id') or customer_data.get('state') or '',
            'country_id': customer_data.get('country_id') or customer_data.get('country') or '',
        }
        
        for key in customer_data.keys():
            if key not in normalized:
                normalized[key] = customer_data[key]
        
        return normalized

    def _normalize_shipping_lines(self, shipping_lines):
        if not isinstance(shipping_lines, list):
            return []
        
        normalized = []
        for line in shipping_lines:
            if not isinstance(line, dict):
                continue
            
            normalized_line = {
                'shipping_code': line.get('shipping_code') or line.get('code') or line.get('carrier') or None,
                'shipping_method': line.get('shipping_method') or line.get('method') or line.get('carrier_name') or None,
                'price': line.get('price') or line.get('cost') or line.get('amount') or 0,
                'description': line.get('description') or line.get('name') or None,
                'tracking_number': line.get('tracking_number') or line.get('tracking') or None,
                'tracking_url': line.get('tracking_url') or None,
            }
            
            for key in line.keys():
                if key not in normalized_line:
                    normalized_line[key] = line[key]
            
            normalized.append(normalized_line)
        
        return normalized

    def _merge_order_note(self, existing_note, extra_fields):
        payload = {}
        if existing_note:
            try:
                parsed = json.loads(existing_note)
                if isinstance(parsed, dict):
                    payload = parsed
            except Exception:
                payload = {"note": existing_note}

        for key, value in extra_fields.items():
            if value is None:
                continue
            payload[key] = value

        return json.dumps(payload)

    @http.route(
        '/garm/orders',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False
    )
    def list_orders(self, **kwargs):
        oauth = authenticate()

        if not oauth:
            return Response(
                json.dumps({
                    "error": "unauthorized",
                    "error_description": "Unauthorized access"
                }),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

        try:
            count_only = kwargs.get('count_only', None)
            limit = max(1, int(kwargs.get('limit', 100)))
            cursor = kwargs.get('cursor', None)
            status = kwargs.get('status', None)
        except ValueError:
            limit = 100
            cursor = None
            status = None
            count_only = None

        order_model = request.env['sale.order'].sudo()
        domain = []

        if status:
            status_type = str(status).lower().strip()
            if status_type in ['draft', 'sent', 'sale', 'done', 'cancel']:
                domain.append(('state', '=', status_type))

        total_count = order_model.search_count(domain)

        if count_only and count_only == '1':
            return Response(
                json.dumps({
                    "metadata": {
                        "total_count": total_count
                    }
                }),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )

        if cursor:
            try:
                last_id = int(base64.b64decode(cursor).decode('utf-8'))
                domain.append(('id', '>', last_id))
            except Exception:
                return Response(
                    json.dumps({
                        "error": "invalid_cursor",
                        "error_description": "The provided cursor is invalid."
                    }),
                    status=400,
                    headers=[('Content-Type', 'application/json')]
                )

        orders = order_model.search_read(
            domain=domain,
            limit=limit + 1,
            order='id asc'
        )

        has_next = len(orders) > limit
        if has_next:
            orders = orders[:limit]
            next_cursor = base64.b64encode(str(orders[-1]['id']).encode('utf-8')).decode('utf-8')
        else:
            next_cursor = None

        order_ids = [order['id'] for order in orders]
        order_lines = request.env['sale.order.line'].sudo().search_read(
            domain=[('order_id', 'in', order_ids)],
            fields=[
                'id',
                'order_id',
                'product_id',
                'name',
                'product_uom_qty',
                'qty_delivered',
                'price_unit',
                'discount',
                'price_subtotal',
                'price_total',
                'state'
            ]
        )

        lines_by_order = {}
        for line in order_lines:
            order_id = line.get('order_id', [None])[0]
            if order_id not in lines_by_order:
                lines_by_order[order_id] = []
            lines_by_order[order_id].append(self.normalizeOrderLine(line))

        clean_orders = []
        for order in orders:
            clean_orders.append(self._format_order(order, lines_by_order.get(order['id'], [])))

        context = {
            "orders": clean_orders,
            "metadata": {
                "limit": limit,
                "next_cursor": next_cursor,
                "has_next": has_next,
                "total_count": total_count
            }
        }

        return Response(
            json.dumps(context),
            status=200,
            headers=[('Content-Type', 'application/json')]
        )

    @http.route(
        '/garm/order',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def create_order(self, **post):
        oauth = authenticate()

        if not oauth:
            return Response(
                json.dumps({
                    "error": "unauthorized",
                    "error_description": "Unauthorized access"
                }),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

        try:
            if not post and request.httprequest.data:
                try:
                    post = json.loads(request.httprequest.data.decode('utf-8'))
                except ValueError:
                    return Response(
                        json.dumps({
                            "error": "invalid_json",
                            "error_description": "Malformed JSON payload"
                        }),
                        status=400,
                        headers=[('Content-Type', 'application/json')]
                    )

            required_fields = []
            for field in required_fields:
                if not post.get(field, None):
                    return Response(
                        json.dumps({
                            "error": "missing_field",
                            "error_description": f"{field} field is missing"
                        }),
                        status=400,
                        headers=[('Content-Type', 'application/json')]
                    )

            order_vals = {
                'state': post.get('state', 'draft'),
                'note': post.get('note', ''),
            }

            if post.get('website_id', None) is not None:
                order_vals['website_id'] = int(post.get('website_id'))

            if post.get('user_id', None) is not None:
                order_vals['user_id'] = int(post.get('user_id'))

            if post.get('pricelist_id', None) is not None:
                order_vals['pricelist_id'] = int(post.get('pricelist_id'))

            custom_payload = self._extract_custom_order_payload(post)

            shipping_address = custom_payload['shipping_address']
            billing_address = custom_payload['billing_address']
            custom_customer = custom_payload['custom_customer']
            custom_item_lines = custom_payload['custom_item_lines']
            shipping_lines = custom_payload['shipping_lines']
            metadata = custom_payload['order_metadata']
            discount_code = custom_payload['discount_code']

            if not order_vals.get('partner_id') and custom_customer:
                customer_partner = self._resolve_customer_partner(custom_customer)
                if customer_partner:
                    order_vals['partner_id'] = customer_partner.id

            if shipping_address:
                shipping_partner = self._resolve_address_partner(shipping_address, 'delivery')
                if shipping_partner:
                    order_vals['partner_shipping_id'] = shipping_partner.id
            if billing_address:
                billing_partner = self._resolve_address_partner(billing_address, 'invoice')
                if billing_partner:
                    order_vals['partner_invoice_id'] = billing_partner.id

            note_payload = {}
            if order_vals.get('note'):
                try:
                    parsed = json.loads(order_vals.get('note'))
                    if isinstance(parsed, dict):
                        note_payload = parsed
                except Exception:
                    note_payload = {'note': order_vals.get('note')}
            if shipping_address:
                note_payload['shipping_address'] = shipping_address
            if billing_address:
                note_payload['billing_address'] = billing_address
            if custom_customer:
                note_payload['custom_customer'] = custom_customer
            if shipping_lines:
                note_payload['shipping_lines'] = shipping_lines
            if custom_item_lines:
                note_payload['item_lines'] = custom_item_lines
            if discount_code:
                note_payload['discount_code'] = discount_code
            note_payload['metadata'] = metadata
            if note_payload:
                order_vals['note'] = json.dumps(note_payload)

            order = request.env['sale.order'].sudo().create(order_vals)

            lines = post.get('lines', [])
            if lines and isinstance(lines, list):
                for line in lines:
                    if not isinstance(line, dict):
                        continue

                    product_id = line.get('product_id')
                    if not product_id:
                        continue

                    product = request.env['product.product'].sudo().browse(int(product_id))
                    if not product.exists():
                        continue

                    order_line_vals = {
                        'order_id': order.id,
                        'product_id': product.id,
                        'product_uom_qty': float(line.get('product_uom_qty', 1)),
                        'price_unit': float(line.get('price_unit', 0.0)),
                        'discount': float(line.get('discount', 0.0)),
                    }

                    if line.get('name'):
                        order_line_vals['name'] = line.get('name')

                    request.env['sale.order.line'].sudo().create(order_line_vals)

            order = order.sudo().read()[0]
            order['lines'] = request.env['sale.order.line'].sudo().search_read(
                domain=[('order_id', '=', order['id'])],
                fields=['id', 'product_id', 'name', 'product_uom_qty', 'price_unit', 'discount', 'price_subtotal', 'price_total']
            )
            order['customer_shipping_address'] = shipping_address
            order['customer_billing_address'] = billing_address
            order['custom_customer'] = custom_customer
            order['shipping_lines'] = shipping_lines
            order['item_lines'] = custom_item_lines or order['lines']
            order['custom_item_lines'] = custom_item_lines
            order['discount_code'] = discount_code
            order['order_metadata'] = metadata
            if order['discount_code'] and isinstance(order['order_metadata'], dict) and 'discount_code' not in order['order_metadata']:
                order['order_metadata']['discount_code'] = order['discount_code']

            return Response(
                json.dumps({
                    'order': self.normalizeOrder(order)
                }),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            return Response(
                json.dumps({
                    "error": "error_found",
                    "error_description": str(e)
                }),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

    @http.route(
        '/garm/order/<int:order_id>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False
    )
    def get_order_by_id(self, order_id, **kwargs):
        oauth = authenticate()

        if not oauth:
            return Response(
                json.dumps({
                    'error': 'unauthorized',
                    'error_description': 'Unauthorized access',
                }),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

        order = request.env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            return Response(
                json.dumps({
                    'error': 'not_found',
                    'error_description': f'Order with ID {order_id} does not exist.',
                }),
                status=404,
                headers=[('Content-Type', 'application/json')]
            )

        lines = request.env['sale.order.line'].sudo().search_read(
            domain=[('order_id', '=', order.id)],
            fields=[
                'id', 'order_id', 'product_id', 'name', 'product_uom_qty',
                'qty_delivered', 'price_unit', 'discount', 'price_subtotal',
                'price_total', 'state',
            ],
        )
        lines = [self.normalizeOrderLine(line) for line in lines]
        return Response(
            json.dumps({'order': self._format_order(order.read()[0], lines)}),
            status=200,
            headers=[('Content-Type', 'application/json')]
        )

    @http.route(
        '/garm/order/<int:order_id>',
        type='http',
        auth='public',
        methods=['PUT'],
        csrf=False
    )
    def update_order(self, order_id, **post):
        oauth = authenticate()

        if not oauth:
            return Response(
                json.dumps({
                    "error": "unauthorized",
                    "error_description": "Unauthorized access"
                }),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

        try:
            if not post and request.httprequest.data:
                try:
                    post = json.loads(request.httprequest.data.decode('utf-8'))
                except ValueError:
                    return Response(
                        json.dumps({
                            "error": "invalid_json",
                            "error_description": "Malformed JSON payload"
                        }),
                        status=400,
                        headers=[('Content-Type', 'application/json')]
                    )

            order = request.env['sale.order'].sudo().browse(order_id)
            if not order.exists():
                return Response(
                    json.dumps({
                        "error": "not_found",
                        "error_description": f"Order with ID {order_id} does not exist."
                    }),
                    status=404,
                    headers=[('Content-Type', 'application/json')]
                )

            update_vals = {}
            if 'partner_id' in post and post.get('partner_id') is not None:
                update_vals['partner_id'] = int(post.get('partner_id'))
            if 'state' in post and post.get('state') is not None:
                update_vals['state'] = post.get('state')
            if 'note' in post and post.get('note') is not None:
                update_vals['note'] = post.get('note')
            if 'website_id' in post and post.get('website_id') is not None:
                update_vals['website_id'] = int(post.get('website_id'))
            if 'user_id' in post and post.get('user_id') is not None:
                update_vals['user_id'] = int(post.get('user_id'))
            if 'pricelist_id' in post and post.get('pricelist_id') is not None:
                update_vals['pricelist_id'] = int(post.get('pricelist_id'))

            custom_payload = self._extract_custom_order_payload(post)
            shipping_address = custom_payload['shipping_address']
            billing_address = custom_payload['billing_address']
            custom_customer = custom_payload['custom_customer']
            custom_item_lines = custom_payload['custom_item_lines']
            shipping_lines = custom_payload['shipping_lines']
            metadata = custom_payload['order_metadata']
            discount_code = custom_payload['discount_code']

            if not order.partner_id and custom_customer:
                customer_partner = self._resolve_customer_partner(custom_customer)
                if customer_partner:
                    update_vals['partner_id'] = customer_partner.id
            if shipping_address:
                shipping_partner = self._resolve_address_partner(shipping_address, 'delivery')
                if shipping_partner:
                    update_vals['partner_shipping_id'] = shipping_partner.id
            if billing_address:
                billing_partner = self._resolve_address_partner(billing_address, 'invoice')
                if billing_partner:
                    update_vals['partner_invoice_id'] = billing_partner.id

            note_payload = {}
            if order.note:
                try:
                    parsed = json.loads(order.note)
                    if isinstance(parsed, dict):
                        note_payload = parsed
                except Exception:
                    note_payload = {'note': order.note}
            if 'note' in post and post.get('note') is not None:
                note_payload['note'] = post.get('note')
            if shipping_address:
                note_payload['shipping_address'] = shipping_address
            if billing_address:
                note_payload['billing_address'] = billing_address
            if custom_customer:
                note_payload['custom_customer'] = custom_customer
            if shipping_lines is not None:
                note_payload['shipping_lines'] = shipping_lines
            if custom_item_lines:
                note_payload['item_lines'] = custom_item_lines
            if discount_code:
                note_payload['discount_code'] = discount_code
            note_payload['metadata'] = metadata
            if note_payload:
                update_vals['note'] = json.dumps(note_payload)

            if update_vals:
                order.write(update_vals)

            lines = post.get('lines', [])
            if lines and isinstance(lines, list):
                for line in lines:
                    if not isinstance(line, dict):
                        continue

                    line_id = line.get('id')
                    if line_id:
                        order_line = request.env['sale.order.line'].sudo().browse(int(line_id))
                        if order_line.exists() and order_line.order_id.id == order.id:
                            line_vals = {}
                            if 'product_id' in line and line.get('product_id') is not None:
                                line_vals['product_id'] = int(line.get('product_id'))
                            if 'product_uom_qty' in line and line.get('product_uom_qty') is not None:
                                line_vals['product_uom_qty'] = float(line.get('product_uom_qty'))
                            if 'price_unit' in line and line.get('price_unit') is not None:
                                line_vals['price_unit'] = float(line.get('price_unit'))
                            if 'discount' in line and line.get('discount') is not None:
                                line_vals['discount'] = float(line.get('discount'))
                            if 'name' in line and line.get('name') is not None:
                                line_vals['name'] = line.get('name')
                            if line_vals:
                                order_line.write(line_vals)
                    else:
                        product_id = line.get('product_id')
                        if not product_id:
                            continue

                        product = request.env['product.product'].sudo().browse(int(product_id))
                        if not product.exists():
                            continue

                        request.env['sale.order.line'].sudo().create({
                            'order_id': order.id,
                            'product_id': product.id,
                            'product_uom_qty': float(line.get('product_uom_qty', 1)),
                            'price_unit': float(line.get('price_unit', 0.0)),
                            'discount': float(line.get('discount', 0.0)),
                            'name': line.get('name', product.name),
                        })

            order = order.sudo().read()[0]
            order['lines'] = request.env['sale.order.line'].sudo().search_read(
                domain=[('order_id', '=', order['id'])],
                fields=['id', 'product_id', 'name', 'product_uom_qty', 'price_unit', 'discount', 'price_subtotal', 'price_total']
            )
            order['customer_shipping_address'] = shipping_address
            order['customer_billing_address'] = billing_address
            order['custom_customer'] = custom_customer
            order['shipping_lines'] = shipping_lines
            order['item_lines'] = custom_item_lines or order['lines']
            order['custom_item_lines'] = custom_item_lines
            order['discount_code'] = discount_code
            order['order_metadata'] = metadata
            if order['discount_code'] and isinstance(order['order_metadata'], dict) and 'discount_code' not in order['order_metadata']:
                order['order_metadata']['discount_code'] = order['discount_code']

            return Response(
                json.dumps({
                    'order': self.normalizeOrder(order)
                }),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            return Response(
                json.dumps({
                    "error": "error_found",
                    "error_description": str(e)
                }),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )