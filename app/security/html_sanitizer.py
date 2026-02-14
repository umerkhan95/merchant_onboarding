"""HTML sanitization to prevent stored XSS."""

from __future__ import annotations

import re

import bleach


class HTMLSanitizer:
    """Sanitizes HTML content before storage.

    Uses bleach to strip all dangerous markup including script tags,
    style tags, and event handler attributes while preserving a safe
    subset of formatting tags.

    Script and style elements are removed entirely (including their
    content) before bleach processes the remaining HTML.
    """

    _ALLOWED_TAGS: frozenset[str] = frozenset({
        "p", "br", "strong", "em", "a",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "span", "div",
    })

    _ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
        "a": ["href", "title"],
    }

    # Patterns to strip script/style elements including their content.
    # re.DOTALL so '.' matches newlines inside multi-line script blocks.
    _STRIP_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"<script[\s>].*?</script>", re.IGNORECASE | re.DOTALL),
        re.compile(r"<style[\s>].*?</style>", re.IGNORECASE | re.DOTALL),
    )

    @staticmethod
    def sanitize(html: str) -> str:
        """Sanitize an HTML string, stripping all disallowed elements.

        Removes script tags, style tags, event handlers (onclick, etc.),
        and any tags/attributes not on the allowlist. Script and style
        elements are removed with their content. Other disallowed tags
        are stripped but their text content is preserved.

        Args:
            html: Raw HTML string to sanitize.

        Returns:
            Sanitized HTML string containing only allowed tags and attributes.
        """
        # First pass: remove script and style elements entirely
        # (bleach's strip=True would keep their text content).
        for pattern in HTMLSanitizer._STRIP_PATTERNS:
            html = pattern.sub("", html)

        # Second pass: bleach handles everything else (disallowed tags,
        # disallowed attributes, event handlers, etc.).
        return bleach.clean(
            html,
            tags=HTMLSanitizer._ALLOWED_TAGS,
            attributes=HTMLSanitizer._ALLOWED_ATTRIBUTES,
            strip=True,
        )
