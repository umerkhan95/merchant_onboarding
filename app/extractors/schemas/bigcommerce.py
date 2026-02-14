"""CSS selector schema for BigCommerce product extraction."""

from __future__ import annotations

BIGCOMMERCE_SCHEMA = {
    "name": "BigCommerce Product",
    "baseSelector": ".productView",
    "fields": [
        {"name": "title", "selector": ".productView-title", "type": "text"},
        {"name": "price", "selector": ".price--withoutTax, .price-section .price", "type": "text"},
        {"name": "description", "selector": ".productView-description", "type": "html"},
        {
            "name": "image",
            "selector": ".productView-image img, .productView-thumbnail img",
            "type": "attribute",
            "attribute": "src",
        },
        {"name": "sku", "selector": "[data-product-sku], .productView-info-value", "type": "text"},
    ],
}
