from __future__ import annotations

import re
from importlib import resources


_DOCUMENT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}\.graphql$")


def load_graphql_document(filename: str) -> str:
    """Load one code-owned GraphQL document from this package."""

    if not _DOCUMENT_NAME.fullmatch(filename):
        raise ValueError("ONES GraphQL document name is invalid")
    try:
        document = resources.files(__package__).joinpath(filename).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise ValueError(f"ONES GraphQL document is missing: {filename}") from exc
    document = document.strip()
    if not document:
        raise ValueError(f"ONES GraphQL document is empty: {filename}")
    return document


__all__ = ["load_graphql_document"]
