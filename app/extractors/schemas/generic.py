"""Generic CSS selector schema with fallback selectors for product extraction."""

from __future__ import annotations

GENERIC_SCHEMA = {
    "name": "Generic Product",
    "baseSelector": (
        "[itemtype*='schema.org/Product'], "
        "[itemtype*='Product'], "
        ".product-detail, "
        ".product-single, "
        ".product__info, "
        "#product-info, "
        "[data-product], "
        "[data-product-id], "
        ".pdp-main, "
        "#product, "
        "main .product"
    ),
    "fields": [
        {
            "name": "title",
            "selector": (
                "[itemprop='name'], "
                "h1.product-title, h1.product-name, h1.product__title, "
                ".product-detail h1, .product-single h1, "
                "[data-product-title], "
                "h1"
            ),
            "type": "text",
        },
        {
            "name": "price",
            "selector": (
                "[itemprop='price'], "
                "[data-price], "
                ".product-price, .price .money, .price .amount, "
                ".current-price, .sale-price, "
                ".price--regular, .price--sale, "
                ".price"
            ),
            "type": "text",
        },
        {
            "name": "currency",
            "selector": (
                "[itemprop='priceCurrency'], "
                "meta[property='product:price:currency'], "
                "[data-currency]"
            ),
            "type": "text",
        },
        {
            "name": "description",
            "selector": (
                "[itemprop='description'], "
                ".product-description, .product__description, "
                ".description, .product-detail__description, "
                "[data-product-description]"
            ),
            "type": "text",
        },
        {
            "name": "image",
            "selector": (
                "[itemprop='image'], "
                ".product-image img, .product__media img, "
                ".gallery img, .product-gallery img, "
                "picture img, "
                "[data-product-image] img"
            ),
            "type": "attribute",
            "attribute": "src",
        },
        {
            "name": "sku",
            "selector": "[itemprop='sku'], .product-sku, .sku, [data-sku], [data-product-sku]",
            "type": "text",
        },
        {
            "name": "vendor",
            "selector": (
                "[itemprop='brand'], "
                ".product-vendor, .product__vendor, "
                ".brand, .brand-name, "
                "[data-vendor]"
            ),
            "type": "text",
        },
        {
            "name": "in_stock",
            "selector": (
                "[itemprop='availability'], "
                ".stock-status, .availability, .product-availability, "
                ".in-stock, .out-of-stock, "
                "[data-availability]"
            ),
            "type": "text",
        },
        {
            "name": "product_url",
            "selector": "link[rel='canonical'], [itemprop='url']",
            "type": "attribute",
            "attribute": "href",
        },
        {
            "name": "product_type",
            "selector": (
                "[itemprop='category'], "
                ".product-type, .product__type, "
                ".breadcrumb li:last-child, "
                "[data-product-type]"
            ),
            "type": "text",
        },
    ],
}
