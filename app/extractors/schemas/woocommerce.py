"""CSS selector schema for WooCommerce HTML product extraction."""

from __future__ import annotations

WOOCOMMERCE_SCHEMA = {
    "name": "WooCommerce Product",
    "baseSelector": ".product, .single-product",
    "fields": [
        {
            "name": "title",
            "selector": ".product_title, .woocommerce-product-title, h1.entry-title",
            "type": "text",
        },
        {
            "name": "price",
            "selector": ".woocommerce-Price-amount, .price ins .amount, .price .amount",
            "type": "text",
        },
        {
            "name": "description",
            "selector": ".woocommerce-product-details__short-description, .product-description",
            "type": "html",
        },
        {
            "name": "image",
            "selector": ".woocommerce-product-gallery img, .wp-post-image",
            "type": "attribute",
            "attribute": "src",
        },
        {"name": "sku", "selector": ".sku, [itemprop='sku']", "type": "text"},
    ],
}
