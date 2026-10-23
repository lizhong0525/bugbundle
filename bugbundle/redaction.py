"""Configurable redaction rules applied before a bundle leaves the machine.

Covers: URL query parameters, form-field values, bearer/JWT-like tokens,
email addresses, and selected DOM regions inside an HTML snapshot.
Password and hidden form fields are redacted unconditionally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Long "header.payload.signature" tokens and Bearer headers.
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
# Generic long hex/base64 secrets in "token=..." / "key: ..." style text.
ASSIGNMENT_TOKEN_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|session[_-]?id|access[_-]?token)"
    r"(\s*[:=]\s*['\"]?)([A-Za-z0-9._~+/=-]{12,})"
)

DEFAULT_SENSITIVE_PARAMS = frozenset(
    {
        "token",
        "access_token",
        "id_token",
        "session",
        "session_id",
        "sid",
        "secret",
        "api_key",
        "apikey",
        "key",
        "password",
        "passwd",
        "pwd",
        "email",
        "auth",
        "signature",
    }
)

DEFAULT_SENSITIVE_FIELDS = frozenset({"password", "passwd", "pwd", "secret", "token"})

EMAIL_PLACEHOLDER = "[REDACTED_EMAIL]"
TOKEN_PLACEHOLDER = "[REDACTED_TOKEN]"
PARAM_PLACEHOLDER = "[REDACTED]"
REGION_PLACEHOLDER = "[REDACTED REGION: {selector}]"


@dataclass
class RedactionRules:
    """User-configurable redaction policy."""

    sensitive_params: set[str] = field(default_factory=lambda: set(DEFAULT_SENSITIVE_PARAMS))
    sensitive_fields: set[str] = field(default_factory=lambda: set(DEFAULT_SENSITIVE_FIELDS))
    dom_selectors: list[str] = field(default_factory=list)
    redact_emails: bool = True
    redact_tokens: bool = True
    extra_param_names: list[str] = field(default_factory=list)

    def all_params(self) -> set[str]:
        return self.sensitive_params | {p.lower() for p in self.extra_param_names}

    def all_fields(self) -> set[str]:
        # Passwords are never optional: they are always redacted.
        return self.sensitive_fields | {"password"} | {f.lower() for f in self.sensitive_fields}


class Redactor:
    """Applies a RedactionRules policy to text, URLs, fields and HTML."""

    def __init__(self, rules: RedactionRules | None = None):
        self.rules = rules or RedactionRules()

    # ------------------------------------------------------------------ URLs
    def redact_url(self, url: str) -> str:
        """Redact sensitive query parameters in a URL."""
        try:
            parts = urlsplit(url)
        except ValueError:
            return self.redact_text(url)
        if not parts.query:
            return url
        sensitive = self.rules.all_params()
        pairs = [
            (k, PARAM_PLACEHOLDER if k.lower() in sensitive else v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit(parts._replace(query=urlencode(pairs)))

    # ------------------------------------------------------------------ text
    def redact_text(self, text: str) -> str:
        """Redact emails and token-like secrets inside free text."""
        if self.rules.redact_tokens:
            text = JWT_RE.sub(TOKEN_PLACEHOLDER, text)
            text = BEARER_RE.sub("Bearer " + TOKEN_PLACEHOLDER, text)
            text = ASSIGNMENT_TOKEN_RE.sub(lambda m: m.group(1) + m.group(2) + TOKEN_PLACEHOLDER, text)
        if self.rules.redact_emails:
            text = EMAIL_RE.sub(EMAIL_PLACEHOLDER, text)
        return text

    # ---------------------------------------------------------------- fields
    def redact_field(self, name: str, value: str) -> str:
        """Redact a form-field value when the field name is sensitive."""
        if name.lower() in self.rules.all_fields():
            return PARAM_PLACEHOLDER
        return self.redact_text(value)

    # ------------------------------------------------------------------ HTML
    def redact_dom(self, html: str) -> str:
        """Replace configured DOM regions and inline secrets in an HTML snapshot.

        Region matching is deliberately simple (stdlib only): each selector may be
        `#id`, `.class` or a tag name; the inner content of every matching element
        is replaced with a placeholder. Malformed selectors raise ValueError.
        """
        for selector in self.rules.dom_selectors:
            html = self._redact_region(html, selector)
        # Never keep password/hidden input values in the snapshot.
        html = re.sub(
            r'(<input\b[^>]*\btype=["\'](?:password|hidden)["\'][^>]*?\bvalue=)["\'][^"\']*["\']',
            r"\1'[REDACTED]'",
            html,
            flags=re.IGNORECASE,
        )
        return self.redact_text(html)

    def _redact_region(self, html: str, selector: str) -> str:
        selector = selector.strip()
        if selector.startswith("#"):
            attr_re = re.compile(
                r'(<(?P<tag>[a-zA-Z][a-zA-Z0-9]*)\b[^>]*\bid=["\']'
                + re.escape(selector[1:])
                + r'["\'][^>]*>)(?P<body>.*?)(</(?P=tag)>)',
                re.DOTALL,
            )
        elif selector.startswith("."):
            attr_re = re.compile(
                r'(<(?P<tag>[a-zA-Z][a-zA-Z0-9]*)\b[^>]*\bclass=["\'][^"\']*\b'
                + re.escape(selector[1:])
                + r'\b[^"\']*["\'][^>]*>)(?P<body>.*?)(</(?P=tag)>)',
                re.DOTALL,
            )
        elif re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*", selector):
            attr_re = re.compile(
                r'(<(?P<tag>'
                + selector
                + r')\b[^>]*>)(?P<body>.*?)(</(?P=tag)>)',
                re.DOTALL | re.IGNORECASE,
            )
        else:
            raise ValueError(f"Unsupported DOM selector for redaction: {selector!r}")

        placeholder = REGION_PLACEHOLDER.format(selector=selector)
        return attr_re.sub(lambda m: m.group(1) + placeholder + m.group(m.lastindex), html)
