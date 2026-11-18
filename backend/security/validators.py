"""Small, shared validation helpers for API payloads."""

from __future__ import annotations

import re
from typing import Any

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def clean_text(value: Any, *, maximum: int, required: bool = False) -> str:
    text = " ".join(str(value or "").strip().split())
    if required and not text:
        raise ValueError("This field is required.")
    if len(text) > maximum:
        raise ValueError(f"Text must be at most {maximum} characters.")
    return text


def valid_email(value: Any) -> str:
    email = clean_text(value, maximum=150, required=True).lower()
    if not EMAIL_RE.fullmatch(email):
        raise ValueError("Enter a valid email address.")
    return email


def safe_int(value: Any, *, minimum: int, maximum: int, default: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        if default is not None:
            return default
        raise ValueError("A valid integer is required.")
    if number < minimum or number > maximum:
        raise ValueError(f"Value must be between {minimum} and {maximum}.")
    return number

