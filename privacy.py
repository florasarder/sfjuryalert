"""Helpers for handling PII in logs."""

from __future__ import annotations


def redact_email(email: str) -> str:
    """Return a log-safe version of an email: 'f***@gmail.com'."""
    if not email or "@" not in email:
        return "<redacted>"
    local, _, domain = email.partition("@")
    if not local:
        return f"<redacted>@{domain}"
    return f"{local[0]}***@{domain}"
