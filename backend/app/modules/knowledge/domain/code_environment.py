"""Explicit environment selection for code knowledge; never infer a default."""

import re
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError


def environment_code(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 100 or value != value.strip():
        raise CodeKnowledgeError("CODE_ENVIRONMENT_REQUIRED")
    return value


def selected_environment(value: Any, environments: list[dict[str, Any]]) -> dict[str, Any]:
    code = environment_code(value)
    matches = [row for row in environments if row["code"] == code]
    if len(matches) != 1:
        raise CodeKnowledgeError("CODE_ENVIRONMENT_UNAVAILABLE")
    return matches[0]


def user_environment(text: str, environments: list[dict[str, Any]]) -> dict[str, Any]:
    """Recognize a single explicit code/name beside 环境/environment in private input."""
    if not isinstance(text, str) or len(text) > 128000:
        raise CodeKnowledgeError("CODE_ENVIRONMENT_REQUIRED")
    labels = {row[key] for row in environments for key in ("code", "name")} - {""}
    alternatives = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    candidate = rf"(?<![A-Za-z0-9_.-])(?:{alternatives})(?![A-Za-z0-9_.-])"
    if labels and re.search(rf"{candidate}\s*(?:[/、,，]|和|与)\s*{candidate}", text):
        raise CodeKnowledgeError("CODE_ENVIRONMENT_REQUIRED")
    matches = {}
    markers: set[int] = set()
    for row in environments:
        for label in {row["code"], row["name"]} - {""}:
            escaped = re.escape(label)
            prefix = rf"(?:环境|\b(?i:environment))\s*[=:：]\s*[`\"']?{escaped}(?![\w./、-])"
            suffix = rf"(?<![A-Za-z0-9_.-]){escaped}[`\"']?\s*(?:环境|\b(?i:environment)\b)"
            declared = list(re.finditer(prefix, text))
            markers.update(match.start() for match in declared)
            named = label.endswith("环境") and re.search(rf"(?<![A-Za-z0-9_.-]){escaped}", text)
            if declared or re.search(suffix, text) or named:
                matches[row["id"]] = row
    unknown = any(
        match.start() not in markers
        for match in re.finditer(r"(?:环境|\b(?i:environment))\s*[=:：]", text)
    )
    if len(matches) != 1 or unknown:
        raise CodeKnowledgeError("CODE_ENVIRONMENT_REQUIRED")
    return next(iter(matches.values()))
