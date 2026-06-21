"""Shared helpers."""

from __future__ import annotations


def norm_province(province: str) -> str:
    text = province.strip()
    if text.lower().startswith("x"):
        return "x" + text[1:].upper()
    return text
