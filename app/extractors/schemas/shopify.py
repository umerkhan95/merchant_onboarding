"""CSS selector schema for Shopify HTML fallback product extraction."""

from __future__ import annotations

SHOPIFY_SCHEMA = {
    "name": "Shopify Product",
    "baseSelector": ".product, .product-single, [data-product]",
    "fields": [
        {
            "name": "title",
            "selector": ".product__title, .product-single__title, h1.product-title",
            "type": "text",
        },
        {
            "name": "price",
            "selector": ".product__price, .price__regular .price-item, [data-product-price]",
            "type": "text",
        },
        {
            "name": "description",
            "selector": ".product__description, .product-single__description",
            "type": "html",
        },
        {
            "name": "image",
            "selector": ".product__media img, .product-single__photo img",
            "type": "attribute",
            "attribute": "src",
        },
    ],
}
