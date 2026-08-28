import hashlib
import hmac
import json
import logging

import requests

from odoo import api, fields, models
from odoo.tools import html2plaintext


_logger = logging.getLogger(__name__)

_app_url = "http://localhost/garmisland/public/api/odoo/webhook"
_app_secret = "your_app_secret_here"  # Replace with your actual app secret

class GarmWebhookDispatcher(models.AbstractModel):
    _name = 'garm.webhook.dispatcher'
    _description = 'Garm Island webhook dispatcher'

    @api.model
    def dispatch(self, event, record, data=None):
        parameters = self.env['ir.config_parameter'].sudo()
        website_name = self.env['website'].get_current_website().get_base_url()
        webhook_url = _app_url
        secret = _app_secret
        
        payload = {
            'event': event,
            'topic': event.replace('.', '_').upper(),
            'model': record._name,
            "shop_domain": website_name,
            'record_id': record.id,
            'occurred_at': fields.Datetime.now().isoformat(),
            'payload': data if data is not None else self._record_data(record),
        }
        body = json.dumps(payload, default=str, separators=(',', ':'))
        headers = {'Content-Type': 'application/json'}

        # if secret:
        #     signature = hmac.new(
        #         secret.encode(), body.encode(), hashlib.sha256
        #     ).hexdigest()
        #     headers['X-Garm-Signature'] = signature
        _logger.info(f"Dispatching webhook for event {payload}")
        try:
            response = requests.post(
                webhook_url,
                data=body,
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            _logger.exception('Garm webhook failed for event %s', event)

    @api.model
    def _record_data(self, record):
        record = record.sudo()
        if record._name == 'product.template':
            return self._product_data(record)
        if record._name == 'sale.order':
            return self._order_data(record)
        return self._json_safe(record.read()[0])

    @api.model
    def _product_data(self, product):
        product_data = self._json_safe(product.read()[0])
        attribute_data = []
        for line in product.attribute_line_ids:
            values = [{
                'value_id': value.product_attribute_value_id.id,
                'value_name': value.name,
                'price_extra': value.price_extra,
            } for value in line.value_ids]
            attribute_data.append({
                'attribute_line_id': line.id,
                'attribute_id': line.attribute_id.id,
                'attribute_name': line.attribute_id.name,
                'values': values,
            })

        product_data['attribute'] = attribute_data
        product_data['status'] = self._product_status(product_data)
        product_data['slug'] = '%s-%s' % (
            self.env['ir.http']._slugify(product_data.get('name', '')),
            product.id,
        )
        product_data['website_description'] = product_data.get('website_description') or ''
        product_data['description_ecommerce'] = product_data.get('description_ecommerce') or ''
        media = self.env['product.image'].search(
            [('product_tmpl_id', '=', product.id)], limit=1
        )
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        unique_hash = product.write_date.strftime('%Y%m%d%H%M%S') if product.write_date else '1'
        product_data['display_image'] = {
            'id': media.id,
            'name': media.name,
            'url': '%s/web/image?model=product.template&id=%s&field=image_1920&unique=%s' % (
                base_url, product.id, unique_hash,
            ),
        }
        product_data['tags'] = [{
            'tag_id': tag.id,
            'tag_name': tag.name,
            'color_index': tag.color,
        } for tag in product.product_tag_ids]
        product_data['product_variants'] = self._product_variants(product)
        return product_data

    @staticmethod
    def _product_status(product):
        if product.get('active') and not product.get('is_published'):
            return 'draft'
        if product.get('active') and product.get('is_published') and product.get('sale_ok'):
            return 'active'
        if not product.get('active'):
            return 'archived'
        return 'unknown'

    @api.model
    def _product_variants(self, product):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        variants = self.env['product.product'].sudo().search([
            ('product_tmpl_id', '=', product.id),
            ('active', '=', True),
        ])
        result = []
        for variant in variants:
            media = self.env['product.image'].sudo().search(
                [('product_tmpl_id', '=', variant.id)], limit=1
            )
            unique_hash = variant.write_date.strftime('%Y%m%d%H%M%S') if variant.write_date else '1'
            result.append({
                'variant_id': variant.id,
                'sequence': variant.sequence,
                'list_price': variant.price_extra,
                'quantity': variant.qty_available,
                'website_url': variant.website_url,
                'display_image': {
                    'id': media.id,
                    'name': media.name,
                    'url': '%s/web/image?model=product.product&id=%s&field=image_1920&unique=%s' % (
                        base_url, variant.id, unique_hash,
                    ),
                },
                'attribute_data': [{
                    'value_id': value.product_attribute_value_id.id,
                    'value_name': value.name,
                    'attribute_name': value.attribute_id.name,
                } for value in variant.product_template_attribute_value_ids],
            })
        return result

    @api.model
    def _order_data(self, order):
        customer = order.partner_id.sudo()
        order_data = self._json_safe(order.read()[0])
        order_data['customer'] = self._customer_data(customer)
        order_data['lines'] = self._json_safe(self.env['sale.order.line'].sudo().search_read(
            [('order_id', '=', order.id)],
            fields=[
                'id', 'product_id', 'name', 'product_uom_qty', 'price_unit',
                'discount', 'price_subtotal', 'price_total',
            ],
        ))
        note_payload = {}
        if order_data.get('note'):
            note_value = html2plaintext(order_data['note']).strip()
            try:
                parsed = json.loads(note_value)
                note_payload = parsed if isinstance(parsed, dict) else {'note': order_data['note']}
            except (TypeError, ValueError):
                note_payload = {'note': note_value}
        order_data['customer_shipping_address'] = self._address_data(order.partner_shipping_id) or note_payload.get('shipping_address') or note_payload.get('customer_shipping_address') or {}
        order_data['customer_billing_address'] = self._address_data(order.partner_invoice_id) or note_payload.get('billing_address') or note_payload.get('customer_billing_address') or {}
        order_data['custom_customer'] = note_payload.get('custom_customer') or note_payload.get('customer') or {}
        order_data['shipping_lines'] = note_payload.get('shipping_lines') or note_payload.get('shipping_line_details') or []
        order_data['item_lines'] = note_payload.get('item_lines') or order_data['lines']
        order_data['custom_item_lines'] = note_payload.get('custom_item_lines') or []
        order_data['discount_code'] = note_payload.get('discount_code')
        order_data['order_metadata'] = note_payload
        return self._json_safe(order_data)

    @api.model
    def _customer_data(self, customer):
        if not customer:
            return {}
        return self._json_safe({
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
        })

    @api.model
    def _address_data(self, address):
        if not address:
            return {}
        return self._json_safe({
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
        })

    @classmethod
    def _json_safe(cls, value):
        if isinstance(value, dict):
            return {key: cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [cls._json_safe(item) for item in value]
        return value


class GarmProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        dispatcher = self.env['garm.webhook.dispatcher']
        for record in records:
            dispatcher.dispatch('product.created', record)
        return records

    def write(self, vals):
        result = super().write(vals)
        dispatcher = self.env['garm.webhook.dispatcher']
        for record in self:
            dispatcher.dispatch('product.updated', record, {'changes': vals, 'product': dispatcher._record_data(record)})
        return result

    def unlink(self):
        dispatcher = self.env['garm.webhook.dispatcher']
        records = [(record.id, dispatcher._record_data(record)) for record in self]
        result = super().unlink()
        for record_id, data in records:
            dispatcher.dispatch('product.deleted', self.browse(record_id), data)
        return result


class GarmSaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        dispatcher = self.env['garm.webhook.dispatcher']
        for record in records:
            dispatcher.dispatch('order.created', record)
        return records

    def write(self, vals):
        previous_states = {record.id: record.state for record in self}
        result = super().write(vals)
        dispatcher = self.env['garm.webhook.dispatcher']
        for record in self:
            dispatcher.dispatch('order.updated', record, {'changes': vals, 'order': dispatcher._record_data(record)})
            if previous_states.get(record.id) != record.state:
                dispatcher.dispatch('order.status_updated', record, {
                    'previous_status': previous_states.get(record.id),
                    'status': record.state,
                    'order': dispatcher._record_data(record),
                })
        return result

    @api.depends('picking_ids', 'picking_ids.state')
    def _compute_delivery_status(self):
        # override must keep @api.depends, otherwise the ORM loses the recompute trigger and this never runs.
        previous_statuses = {order.id: order.delivery_status for order in self}
        super()._compute_delivery_status()
        dispatcher = self.env['garm.webhook.dispatcher']
        for order in self:
            if previous_statuses.get(order.id) != order.delivery_status:
                dispatcher.dispatch('order.delivery_status_updated', order, {
                    'previous_delivery_status': previous_statuses.get(order.id),
                    'delivery_status': order.delivery_status,
                    'order': dispatcher._record_data(order),
                })


class GarmStockQuant(models.Model):
    _inherit = 'stock.quant'

    def write(self, vals):
        previous_quantities = {}
        if 'quantity' in vals:
            previous_quantities = {quant.id: quant.quantity for quant in self}
        result = super().write(vals)
        if previous_quantities:
            dispatcher = self.env['garm.webhook.dispatcher']
            for quant in self:
                if quant.product_id and previous_quantities.get(quant.id) != quant.quantity:
                    dispatcher.dispatch('product.quantity_updated', quant.product_id.product_tmpl_id, {
                        'product_id': quant.product_id.id,
                        'previous_quantity': previous_quantities.get(quant.id),
                        'quantity': quant.quantity,
                        'quantity_available': quant.product_id.qty_available,
                    })
        return result