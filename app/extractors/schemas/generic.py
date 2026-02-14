"""Generic CSS selector schema with fallback selectors for product extraction."""

from __future__ import annotations

GENERIC_SCHEMA = {
    "name": "Generic Product",
    "baseSelector": "body",
    "fields": [
        {
            "name": "title",
            "selector": "h1, .product-title, .product-name, [itemprop='name']",
            "type": "text",
        },
        {
            "name": "price",
            "selector": ".price, .product-price, [itemprop='price'], .current-price",
            "type": "text",
        },
        {
            "name": "description",
            "selector": ".product-description, [itemprop='description'], .description",
            "type": "text",
        },
        {
            "name": "image",
            "selector": ".product-image img, [itemprop='image'], .gallery img",
            "type": "attribute",
            "attribute": "src",
        },
        {"name": "sku", "selector": "[itemprop='sku'], .product-sku, .sku", "type": "text"},
    ],
}
