"""Shared never-persist and Notion-dashboard sensitivity filters."""

from __future__ import annotations

import re

from .memory import _contains_sensitive

_NOTION_SENSITIVE_PATTERNS = [
    re.compile(r"\bptsd\b", re.I),
    re.compile(r"\bpanic\s+attack\b", re.I),
    re.compile(r"\bsuicid", re.I),
    re.compile(r"\bself[-\s]?harm\b", re.I),
    re.compile(r"\btherapy\b", re.I),
    re.compile(r"\bintimate\b", re.I),
    re.compile(r"\bsex(?:ual)?\b", re.I),
    re.compile(r"\bmedical\s+diagnosis\b", re.I),
]


def is_notion_safe(text: str) -> bool:
    """Stricter than never-persist: keep intimate/personal detail off Notion."""
    if not text or _contains_sensitive(text):
        return False
    return not any(pattern.search(text) for pattern in _NOTION_SENSITIVE_PATTERNS)


def safe_lines(items: list[str], *, for_notion: bool = False) -> list[str]:
    out: list[str] = []
    for item in items:
        text = " ".join(str(item).split()).strip()
        if not text:
            continue
        if for_notion:
            if not is_notion_safe(text):
                continue
        elif _contains_sensitive(text):
            continue
        out.append(text)
    return out
