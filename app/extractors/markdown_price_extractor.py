"""Extract price, title, and currency from rendered markdown text.

Stateless utility — no LLM, no browser, no network. Works on the markdown
output that crawl4ai produces from a rendered product page.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Currency patterns ──────────────────────────────────────────────────

# Symbol → ISO code mapping
_SYMBOL_TO_CODE: dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "₩": "KRW",
    "₽": "RUB",
    "R$": "BRL",
    "kr": "SEK",  # also NOK/DKK — we default to SEK
    "zł": "PLN",
    "CHF": "CHF",
    "A$": "AUD",
    "C$": "CAD",
    "NZ$": "NZD",
    "HK$": "HKD",
    "S$": "SGD",
}

# ISO currency codes (3 uppercase letters) that may appear near a number
_ISO_CODES = frozenset({
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF", "SEK", "NOK",
    "DKK", "PLN", "CZK", "HUF", "INR", "KRW", "BRL", "RUB", "HKD", "SGD",
    "MXN", "ZAR", "TRY", "THB", "MYR", "PHP", "IDR", "TWD", "AED", "SAR",
    "CNY", "VND", "BGN", "RON", "HRK", "ILS", "CLP", "COP", "PEN", "ARS",
    "UAH", "KZT", "QAR", "KWD", "BHD", "OMR", "JOD", "EGP", "NGN", "KES",
})

# Matches prices like: $49.99, €29,90, 1,299.99, 49.99, EUR 29.90
# Captures: optional currency symbol/code, digits with separators, decimal part
_PRICE_RE = re.compile(
    r"""
    (?:                             # Optional leading currency
        (?P<sym_pre>[€£¥₹₩₽]|      # Single-char symbols
           (?:R\$|A\$|C\$|NZ\$|HK\$|S\$|\$)|  # Multi-char symbols (R$, A$, etc.) or bare $
           (?:kr|zł|CHF)            # Word-like symbols
        )
        \s*
    )?
    (?P<amount>
        \d{1,3}(?:[,.\s]\d{3})*    # Thousands-separated integer part
        (?:[.,]\d{1,2})?           # Optional decimal part
        |
        \d+[.,]\d{1,2}             # Simple decimal (49.99, 29,90)
    )
    (?:
        \s*
        (?P<sym_post>[€£¥₹₩₽]|    # Trailing currency symbol
           (?:kr|zł)
        )
    )?
    (?:
        \s+
        (?P<code>[A-Z]{3})         # Trailing ISO code (e.g. "49.99 EUR")
    )?
    """,
    re.VERBOSE,
)

# Pre-price ISO code: "EUR 29.90", "USD 49.99"
_CODE_PRICE_RE = re.compile(
    r"""
    (?P<code>[A-Z]{3})
    \s+
    (?P<amount>
        \d{1,3}(?:[,.\s]\d{3})*
        (?:[.,]\d{1,2})?
        |
        \d+[.,]\d{1,2}
    )
    """,
    re.VERBOSE,
)

# Lines that are clearly NOT product prices (cart totals, shipping, add-ons, etc.)
_NOISE_PATTERNS = re.compile(
    r"(?i)\b(?:shipping|subtotal|total|tax|discount|coupon|cart|"
    r"was\s+\$|original|compare|regular|list\s+price|you\s+save|"
    r"msrp|rrp|from\s+\$|starting\s+at|add\s+to|"
    r"rug\s+pad|protection\s+plan|warranty|accessory|"
    r"free\s+shipping|estimated|per\s+month|\/month|installment)\b"
)


def _normalize_amount(raw: str) -> str | None:
    """Convert a captured amount string to a clean decimal string.

    Handles both US format (1,299.99) and European format (1.299,99).
    Returns None for obviously invalid amounts.
    """
    cleaned = raw.replace(" ", "")

    if not cleaned or not any(c.isdigit() for c in cleaned):
        return None

    # Determine decimal separator heuristic:
    # If string ends with ,XX (2 digits) → European format (comma is decimal)
    # If string ends with .XX (2 digits) → US format (dot is decimal)
    # If only one separator type exists and it's followed by 3 digits → thousands sep
    if re.search(r",\d{2}$", cleaned) and "." in cleaned:
        # European: 1.299,90 → 1299.90
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif re.search(r",\d{2}$", cleaned):
        # Bare European: 29,90 → 29.90
        cleaned = cleaned.replace(",", ".")
    else:
        # US format or integer: remove comma thousands separators
        cleaned = cleaned.replace(",", "")

    try:
        val = float(cleaned)
    except ValueError:
        return None

    if val <= 0 or val > 1_000_000:
        return None

    return f"{val:.2f}"


def _resolve_currency(
    sym_pre: str | None,
    sym_post: str | None,
    code: str | None,
) -> str | None:
    """Resolve currency from captured groups."""
    if code and code in _ISO_CODES:
        return code
    sym = (sym_pre or sym_post or "").strip()
    if sym:
        return _SYMBOL_TO_CODE.get(sym)
    return None


def extract_price(text: str) -> tuple[str, str | None] | None:
    """Extract the first credible price + currency from text.

    Returns:
        (amount_str, currency_code_or_None) or None if no price found.
    """
    # Try ISO-code-first pattern: "EUR 29.90"
    for m in _CODE_PRICE_RE.finditer(text):
        code = m.group("code")
        if code not in _ISO_CODES:
            continue
        amount = _normalize_amount(m.group("amount"))
        if amount:
            return amount, code

    # Try symbol/amount pattern
    for m in _PRICE_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end]

        if _NOISE_PATTERNS.search(line):
            continue

        amount = _normalize_amount(m.group("amount"))
        if not amount:
            continue

        currency = _resolve_currency(
            m.group("sym_pre"),
            m.group("sym_post"),
            m.group("code"),
        )
        return amount, currency

    return None


def extract_title(markdown: str) -> str | None:
    """Extract product title from markdown headings.

    Prefers H1, then H2. Falls back to first prominent bold line.
    """
    # H1: "# Title"
    m = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    if m:
        title = m.group(1).strip()
        if 3 <= len(title) <= 300:
            return title

    # H2: "## Title"
    m = re.search(r"^##\s+(.+)$", markdown, re.MULTILINE)
    if m:
        title = m.group(1).strip()
        if 3 <= len(title) <= 300:
            return title

    # Bold text at start of line: "**Title**"
    m = re.search(r"^\*\*(.+?)\*\*", markdown, re.MULTILINE)
    if m:
        title = m.group(1).strip()
        if 3 <= len(title) <= 300:
            return title

    return None


def extract(markdown: str, url: str = "") -> dict:
    """Extract price, title, and currency from markdown text.

    Args:
        markdown: Rendered page markdown (preferably fit_markdown for less noise).
        url: Page URL (for logging).

    Returns:
        Dict with available keys: {title, price, currency}. May be partial or empty.
    """
    result: dict = {}

    title = extract_title(markdown)
    if title:
        result["name"] = title

    price_data = extract_price(markdown)
    if price_data:
        amount, currency = price_data
        result["price"] = amount
        if currency:
            result["currency"] = currency

    if result:
        logger.debug("Markdown extraction from %s: %s", url, result)
    else:
        logger.debug("No product data extracted from markdown for %s", url)

    return result
