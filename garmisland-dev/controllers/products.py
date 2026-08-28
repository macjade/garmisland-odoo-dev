from odoo import http
from odoo.http import request, Response
from datetime import datetime, timedelta
import logging
import json
import math
import base64
from urllib.parse import parse_qsl
from .oauth import authenticate

logger = logging.getLogger(__name__)

logger.info(">>>>>>>> PRODUCT CONTROLLER FILE IS LOADED BY ODOO <<<<<<<<")

class GarmProductController(http.Controller):

    def normalizeProducts(self, product):
        result = {}
        for key, val in product.items():
            # Convert non-serializable fields (like dates or custom objects) into safe types
            if isinstance(val, tuple):
                result[key] = list(val) # Convert tuple to JSON-friendly list
            else:
                try:
                    json.dumps(val) # Test if it can be serialized
                    result[key] = val
                except TypeError:
                    result[key] = str(val) # Fallback to string representation

        return result

    def normalizeListProducts(self, product):
            result = []
            for val in product:
                # Convert non-serializable fields (like dates or custom objects) into safe types
                if isinstance(val, tuple):
                    result.append(list(val)) # Convert tuple to JSON-friendly list
                if isinstance(val, dict):
                    result.append(self.normalizeProducts(val)) # Convert tuple to JSON-friendly list
                else:
                    try:
                        json.dumps(val) # Test if it can be serialized
                        result.append(val)
                    except TypeError:
                        result.append(str(val)) # Fallback to string representation
    
            return result

    def getProductStatus(self, product):

        if product['active'] and not product['is_published']:
            return "draft"

        if product['active'] and product['is_published'] and product['sale_ok']:
            return "active"

        if not product['active']:
            return "archived"
        
        return "unknown"

    def setProductStatus(self, status):
        
        if status == "active":
            
            return {
                "active": True,
                "is_published": True,
                "sale_ok": True
            }

        if status == "archived":
            return {
                "active": False,
                "is_published": False,
                "sale_ok": False
            }
        
        return {
            "active": True,
            "is_published": False
        }

    def productVariantMap(self, product):
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        variants = request.env["product.product"].sudo().search(
            domain=[('product_tmpl_id', '=', product.id), ('active', '=', True)]
        )

        variant_map = []

        for variant in variants:
            website_url             = variant.website_url
            website_param_split     = str(website_url).split("#")
            attribute_values        = None

            unique_vr_hash = variant.write_date.strftime('%Y%m%d%H%M%S') if variant.write_date else '1'
            variant_image_url = f"{base_url}/web/image?model=product.product&id={variant.id}&field=image_1920&unique={unique_vr_hash}"
            
            vr_media = request.env['product.image'].search([('product_tmpl_id', '=', variant.id)])

            if len(website_param_split) > 1: 
                param_values  = website_param_split[1]
                param_obj     = dict(parse_qsl(param_values))

                if param_obj.get('attribute_values', None):
                    attribute_values = param_obj["attribute_values"]
            
            attribute_data = [];

            for ptav in variant.product_template_attribute_value_ids:

                attribute_name = ptav.attribute_id.name
                
                value_name = ptav.name  
                
                attribute_data.append({
                    "value_id": ptav.product_attribute_value_id.id,
                    "value_name": value_name,
                    "attribute_name": attribute_name 
                })

            variant_map.append({
                "variant_id"    : variant.id,
                "sequence"      : variant.sequence,
                "list_price"    : variant.price_extra,
                "quantity"      : variant.qty_available,
                'website_url'   : variant.website_url,
                'display_image' : {
                    'id': vr_media.id,
                    'name': vr_media.name,
                    'url': variant_image_url
                },
                'attribute_data': attribute_data
            })

        return variant_map

    def addCustomProductFields(self, product, products_data, serialized_attributes):
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')

        unique_hash = product.write_date.strftime('%Y%m%d%H%M%S') if product.write_date else '1'
        main_image_url = f"{base_url}/web/image?model=product.template&id={product.id}&field=image_1920&unique={unique_hash}"
        
        media = request.env['product.image'].search([('product_tmpl_id', '=', product.id)])
        tags_data = []
        for tag in product['product_tag_ids']:
            tags_data.append({
                'tag_id': tag['id'],
                'tag_name': tag['name'],
                'color_index': tag['color']
            })

        products_data["attribute"] = serialized_attributes
        products_data['status'] = self.getProductStatus(products_data)
        products_data['slug'] = f"{request.env['ir.http']._slugify(products_data['name'])}-{products_data['id']}"
        products_data['website_description'] = products_data['website_description'] or ''
        products_data['description_ecommerce'] = products_data['description_ecommerce'] or ''
        products_data['display_image'] = {
            'id': media.id,
            'name': media.name,
            'url': main_image_url
        }
        products_data['tags'] = tags_data


        
        products_data['product_variants'] = self.productVariantMap(product)
        return products_data

    @http.route(
        '/garm/products',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False
    )
    def products(self, **kwargs):
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
            cat_id = kwargs.get('category', None)
        except ValueError:
            limit = 150
            status = None
            cursor = None
            cat_id = None
            count_only = None

        product_model = request.env["product.template"].sudo()
        
        domain = []

        if status:
            status_type = str(status).lower().strip()
            if status_type == "draft":

                domain.append(('active', '=', True))
                domain.append(('is_published', '=', False))

            elif status_type == "active":

                domain.append(('active', '=', True))
                domain.append(('sale_ok', '=', True))
                domain.append(('is_published', '=', True))

            elif status_type == "archived":

                domain.append(('active', '=', False))

        if cat_id:
            domain.append(('categ_id', 'child_of', int(cat_id)))

        total_count = product_model.search_count(
            domain=domain
        )

        if count_only and count_only == "1":
            context = {
                "metadata": {
                    "total_count": total_count
                }
            }

            return Response(
                json.dumps(context),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )


        if cursor:
            try:
                # Decode base64 cursor to get the last seen ID
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

        products_data = product_model.search(
            domain=domain,
            limit=limit + 1,
            order="id asc"
        )

        has_next = len(products_data) > limit

        if has_next:
            products_data = products_data[:limit]

            # Create next cursor using the ID of the very last item in our page slice
            next_last_id = str(products_data[-1]['id']).encode('utf-8')
            next_cursor = base64.b64encode(next_last_id).decode('utf-8')

        else:
            next_cursor = None

        clean_products = []
        for prod in products_data:
            attribute_lines = request.env["product.template.attribute.line"].sudo().search(
                domain=[('product_tmpl_id', '=', prod.id)]
            )
    
            serialized_attributes = []
            for line in attribute_lines:
                
                tmpl_attribute_values = request.env["product.template.attribute.value"].sudo().search([
                    ('product_tmpl_id', '=', prod.id),
                    ('attribute_id', '=', line.attribute_id.id)
                ])
    
                values_list = []
                for tmpl_val in tmpl_attribute_values:
                    values_list.append({
                        "value_id": tmpl_val.product_attribute_value_id.id, # The core global value ID
                        "value_name": tmpl_val.name,                         # The name (e.g., "XL")
                        "price_extra": tmpl_val.price_extra                 # The variant surcharge price (e.g., 5.0)
                    })
    
                serialized_attributes.append({
                    "attribute_line_id": line.id,
                    "attribute_id": line.attribute_id.id,
                    "attribute_name": line.attribute_id.name,
                    "values": values_list
                })

            prod_obj = self.normalizeProducts(prod.read()[0])
            prod_obj = self.addCustomProductFields(prod, prod_obj, serialized_attributes)
            # prod_obj['attribute'] = serialized_attributes
            # prod_obj['status'] = self.getProductStatus(prod_obj)
            clean_products.append(prod_obj)

        context = {
            "products": clean_products,
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
        '/garm/product/<int:product_id>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False
    )
    def get_product_by_id(self, product_id, **kwargs):
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

        product = request.env["product.template"].sudo().browse(product_id)

        if not product.exists():
            return Response(
                json.dumps({
                    "error": "not_found",
                    "error_description": f"Product with ID {product_id} does not exist."
                }),
                status=404,
                headers=[('Content-Type', 'application/json')]
            )
        
        product_obj = product.read()[0]

        products_data = self.normalizeProducts(product_obj)
        attribute_lines = request.env["product.template.attribute.line"].sudo().search(
            domain=[('product_tmpl_id', '=', product_id)]
        )

        serialized_attributes = []
        for line in attribute_lines:
            
            tmpl_attribute_values = request.env["product.template.attribute.value"].sudo().search([
                ('product_tmpl_id', '=', product_id),
                ('attribute_id', '=', line.attribute_id.id)
            ])

            values_list = []
            for tmpl_val in tmpl_attribute_values:
                values_list.append({
                    "value_id": tmpl_val.product_attribute_value_id.id, # The core global value ID
                    "value_name": tmpl_val.name,                         # The name (e.g., "XL")
                    "price_extra": tmpl_val.price_extra                 # The variant surcharge price (e.g., 5.0)
                })

            serialized_attributes.append({
                "attribute_line_id": line.id,
                "attribute_id": line.attribute_id.id,
                "attribute_name": line.attribute_id.name,
                "values": values_list
            })

        products_data = self.addCustomProductFields(product, products_data, serialized_attributes)

        context = {
            "product": products_data
        }

        return Response(
            json.dumps(context),
            status=200,
            headers=[('Content-Type', 'application/json')]
        )

    @http.route(
        '/garm/product/categories',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False
    )
    def product_categories(self, **kwargs):
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
    
            category_model = request.env["product.category"].sudo()
            
            domain = []
    
    
            total_count = category_model.search_count(
                domain=domain
            )
    
            categories_data = category_model.search_read(
                domain=domain,
                fields=["id", "name", "parent_id", "complete_name"],
                order="complete_name asc"
            )
    
            
            clean_categories = []
            for category in categories_data:
                category_obj = self.normalizeProducts(category)

                product_count = request.env["product.template"].sudo().search_count([
                    ('categ_id', 'child_of', category_obj['id'])
                ])

                category_obj['product_count'] = product_count

                clean_categories.append(category_obj)
    
            context = {
                "categories": clean_categories,
                "metadata": {
                    "total_count": total_count
                }
            }
    
            return Response(
                json.dumps(context),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )

    @http.route(
        '/garm/product/<int:product_id>/variants',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False
    )
    def product_variants(self, product_id, **kwargs):
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

            product = request.env["product.template"].sudo().browse(product_id)

            if not product.exists():
                return Response(
                    json.dumps({
                        "error": "product_not_found",
                        "error_description": "Product not found"
                    }), 
                    status=400,
                    headers=[('Content-Type', 'application/json')]
                )
    
            variants = request.env["product.product"].sudo().search_read(
                domain=[('product_tmpl_id', '=', product_id), ('active', '=', True)]
            )
    
            
            clean_variants = []

            for variant in variants:
                variant_obj = self.normalizeProducts(variant)

                clean_variants.append(variant_obj)
    
            context = {
                "variants": clean_variants
            }
    
            return Response(
                json.dumps(context),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )

    @http.route(
        '/garm/product/<int:product_id>/attributes',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False
    )
    def product_attributes(self, product_id, **kwargs):
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

            product = request.env["product.template"].sudo().browse(product_id)

            if not product.exists():
                return Response(
                    json.dumps({
                        "error": "product_not_found",
                        "error_description": "Product not found"
                    }), 
                    status=400,
                    headers=[('Content-Type', 'application/json')]
                )

            structured_attributes = []

            for line in product.attribute_line_ids:
                # Gather all individual value options defined for this product line
                values_list = []
                
                for val in line.value_ids:
                    values_list.append({
                        "value_id": val.id,
                        "value_name": val.name
                    })

                # Append the parent attribute along with its choices
                structured_attributes.append({
                    "attribute_line_id": line.id,
                    "attribute_id": line.attribute_id.id,
                    "attribute_name": line.attribute_id.name, # e.g., "Color" or "Size"
                    "values": values_list                      # e.g., [{"value_id": 1, "value_name": "Red"}]
                })
    
            context = {
                "attributes": structured_attributes
            }
    
            return Response(
                json.dumps(context),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )


    def setProductTags(self, tags):
        tag_commands = []
            
        if tags and isinstance(tags, list):
            for tag_name in tags:
                tag_name = str(tag_name).lower().strip()

                tag = request.env['product.tag'].search([('name', '=', tag_name)], limit=1)

                if not tag:
                    tag = request.env['product.tag'].sudo().create({'name': tag_name})
                
                tag_commands.append((4, tag.id))

        return {
            "product_tag_ids": tag_commands
        }

    def setProductVariant(self, attributes):
        # Process attributes to build the variants
        if attributes and isinstance(attributes, list):
            attribute_line_commands = []
            
            for attr_data in attributes:
                attr_name = attr_data.get('name')
                value_names = attr_data.get('values', [])
                
                if not attr_name or not value_names:
                    continue
                    
                # 1. Find or create the master Attribute (e.g., "Color")
                attribute = request.env['product.attribute'].sudo().search([('name', '=', attr_name)], limit=1)
                if not attribute:
                    attribute = request.env['product.attribute'].sudo().create({'name': attr_name})
                
                # 2. Find or create the Attribute Values (e.g., "Red", "Blue")
                value_ids = []
                for val_name in value_names:
                    value = request.env['product.attribute.value'].sudo().search([
                        ('name', '=', val_name),
                        ('attribute_id', '=', attribute.id)
                    ], limit=1)
                    if not value:
                        value = request.env['product.attribute.value'].sudo().create({
                            'name': val_name,
                            'attribute_id': attribute.id
                        })
                    value_ids.append(value.id)
                
                # 3. Use Odoo command (0, 0, vals) to create a new attribute line item
                if value_ids:
                    attribute_line_commands.append((0, 0, {
                        'attribute_id': attribute.id,
                        'value_ids': [(6, 0, value_ids)]  # Link all value IDs to this line
                    }))
            
            return {
                "attribute_line_ids": attribute_line_commands
            }

        return {}

    def updateProductVariant(self, product, variant_items):
        if variant_items and isinstance(variant_items, dict):
            product_variants = self.productVariantMap(product)

            for product_variant in product_variants:
                attr_comb = "".join(f"_value['{value_name}']" for key, value_name in product_variant.items())

                if variant_items.get(attr_comb, None):
                    variant = request.env['product.product'].sudo().browse(product_variant["variant_id"])

                    if variant:
                        variant.sudo().write(variant_items[attr_comb])
                        variant_item = variant_items[attr_comb]

                        if variant_item.get('lst_price', None):
                            new_price = float(variant_item['lst_price'])
                            base_template_price = variant.product_tmpl_id.list_price
                            # Calculate required variance relative to the base template catalog price
                            variant.price_extra = new_price - base_template_price

                        if variant_item.get('qty_available', None):
                            new_qty = float(variant_item['qty_available'])
                            
                            # Use Odoo's standard core stock change wizard mechanism
                            qty_wizard = request.env['stock.change.product.qty'].create({
                                'product_id': variant.id,
                                'new_quantity': new_qty,
                            })
                            # Triggers internal stock moves to reconcile inventory
                            qty_wizard.change_product_qty()


    @http.route(
        '/garm/product',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def create_product(self, **post):
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

            required_fields = ["status"]
            optional_fields = ["attributes", "variant_items", "tag_names"]

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

            product_val = {
                **post, 
                **self.setProductStatus(post.get("status", "")),
                **self.setProductTags(post.get("tag_names", None)),
                **self.setProductVariant(post.get("attributes", None))
            }

            variant_items = post.get("variant_items", None)

            product_val = {k: v for k, v in product_val.items() if k not in [*required_fields, *optional_fields]}
            

            # Create the product template record
            new_product = request.env['product.template'].sudo().create(product_val)
            
            if variant_items:
                self.updateProductVariant(new_product, variant_items)

            context = {
                'product': self.normalizeProducts(new_product.read()[0])
            }

            return Response(
                json.dumps(context),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            
            context = {
                'error': 'error_found',
                'error_description': str(e)
            }
            
            return Response(
                json.dumps(context),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )
    

    @http.route(
        '/garm/product/<int:product_id>',
        type='http',
        auth='public',
        methods=['PUT'],
        csrf=False
    )
    def update_product(self, product_id, **post):
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

            required_fields = ["status"]
            optional_fields = ["attributes", "variant_items", "tag_names"]

            product_val = {
                **post, 
                **self.setProductStatus(post.get("status", "")),
                **self.setProductTags(post.get("tag_names", None)),
                **self.setProductVariant(post.get("attributes", None))
            }

            variant_items = post.get("variant_items", None)

            product_val = {k: v for k, v in product_val.items() if k not in [*required_fields, *optional_fields]}

            product = request.env["product.template"].sudo().browse(product_id)

            if not product.exists():
                return Response(
                    json.dumps({
                        "error": "not_found",
                        "error_description": f"Product with ID {product_id} does not exist."
                    }),
                    status=404,
                    headers=[('Content-Type', 'application/json')]
                )

            product.sudo().write(product_val)

            if variant_items:
                self.updateProductVariant(product, variant_items)
            
            context = {
                'product': self.normalizeProducts(product.read()[0])
            }

            return Response(
                json.dumps(context),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            
            context = {
                'error': 'error_found',
                'error_description': str(e)
            }
            
            return Response(
                json.dumps(context),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

    @http.route(
        '/garm/product/<int:product_id>',
        type='http',
        auth='public',
        methods=['DELETE'],
        csrf=False
    )
    def delete_product(self, product_id, **kwargs):
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

        product = request.env["product.template"].sudo().browse(product_id)

        if not product.exists():
            return Response(
                json.dumps({
                    "error": "not_found",
                    "error_description": f"Product with ID {product_id} does not exist."
                }),
                status=404,
                headers=[('Content-Type', 'application/json')]
            )

        try:
            variants = request.env['product.product'].sudo().search([
                ('product_tmpl_id', '=', product_id),
                ('active', 'in', [True, False])
            ])
            variant_count = len(variants)

            if variants:
                variants.unlink()

            product.unlink()

            return Response(
                json.dumps({
                    "deleted": True,
                    "product_id": product_id,
                    "variants_deleted": variant_count
                }),
                status=200,
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            return Response(
                json.dumps({
                    "error": "delete_failed",
                    "error_description": str(e)
                }),
                status=400,
                headers=[('Content-Type', 'application/json')]
            )

        