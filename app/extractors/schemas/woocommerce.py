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
        {
            "name": "sku",
            "selector": ".sku, [itemprop='sku']",
            "type": "text",
        },
        {
            "name": "vendor",
            "selector": ".posted_in a, [itemprop='brand'], .product_meta .brand",
            "type": "text",
        },
        {
            "name": "in_stock",
            "selector": ".stock, .availability, [itemprop='availability']",
            "type": "text",
        },
        {
            "name": "product_type",
            "selector": ".posted_in a, .product_meta .product-cat, .breadcrumb li:last-child",
            "type": "text",
        },
        {
            "name": "product_url",
            "selector": "link[rel='canonical']",
            "type": "attribute",
            "attribute": "href",
        },
        {
            "name": "currency",
            "selector": ".woocommerce-Price-currencySymbol, [itemprop='priceCurrency']",
            "type": "text",
        },
    ],
}
