# Garm Island webhooks

Configure the outbound webhook with Odoo system parameters:

- `garmisland.webhook.url`: destination URL. Webhooks are disabled when empty.
- `garmisland.webhook.secret`: optional secret used to create the HMAC-SHA256 `X-Garm-Signature` header.

The dispatcher emits JSON events for `product.created`, `product.updated`,
`product.deleted`, `order.created`, `order.updated`, and `order.status_updated`.
Product events use `product.template`; order events use `sale.order`.