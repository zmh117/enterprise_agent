"""Separate internal code-answer references from user-visible business prose."""

import re


_INTERNAL_REFERENCE = re.compile(r"<!--\s*code-answer:.*?-->", re.DOTALL)


def strip_code_answer_references(answer: str) -> str:
    """The recorder consumes references first; chat, reports and delivery omit them."""
    cleaned, count = _INTERNAL_REFERENCE.subn("", answer)
    return cleaned.rstrip() if count else answer
