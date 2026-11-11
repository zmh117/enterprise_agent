"""Bounded source Grep normalization; correction never guesses paths or patterns."""

import re
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError

TYPE_GLOBS = {
    "cpp": ("*.c", "*.cc", "*.cpp", "*.cxx", "*.h", "*.hh", "*.hpp", "*.hxx"),
    "c": ("*.c", "*.h"),
    "vue": ("*.vue",),
    "js": ("*.js", "*.jsx", "*.mjs", "*.cjs"),
    "ts": ("*.ts", "*.tsx"),
    "json": ("*.json",),
    "xml": ("*.xml",),
    "java": ("*.java",),
    "py": ("*.py",),
    "cs": ("*.cs",),
    "sql": ("*.sql",),
}


def invalid(field: str) -> CodeKnowledgeError:
    return CodeKnowledgeError("CODE_SOURCE_SEARCH_INVALID", field)


def expand_glob(value: Any) -> tuple[str, ...]:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or value.startswith(("/", "!", "-"))
        or any(c in value for c in "\\\x00")
        or ".." in value.split("/")
        or ".svn" in value.casefold()
    ):
        raise invalid("glob")
    if not any(c in value for c in "{},"):
        return (value,)
    match = re.fullmatch(r"([^{}]*)\{([^{}]+)\}([^{}]*)", value)
    if not match or "," in match[1] + match[3]:
        raise invalid("glob")
    choices = match[2].split(",")
    if not 2 <= len(choices) <= 8 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", c) for c in choices):
        raise invalid("glob")
    expanded = tuple(match[1] + c + match[3] for c in choices)
    # Validate expanded paths too; braces cannot smuggle parent traversal.
    for item in expanded:
        expand_glob(item)
    return expanded


def search_options(arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "path",
        "pattern",
        "glob",
        "type",
        "output_mode",
        "-i",
        "-n",
        "-A",
        "-B",
        "-C",
        "head_limit",
        "offset",
        "multiline",
    }
    if set(arguments) - allowed:
        raise invalid("fields")
    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not 1 <= len(pattern) <= 1024 or "\x00" in pattern:
        raise invalid("pattern")
    mode = arguments.get("output_mode", "content")
    if mode not in {"content", "files_with_matches"}:
        raise invalid("output_mode")
    if arguments.get("multiline", False) is not False:
        raise invalid("multiline")
    if type(arguments.get("offset", 0)) is not int or arguments.get("offset", 0) != 0:
        raise invalid("offset")
    globs = expand_glob(arguments.get("glob", "*"))
    kind = arguments.get("type")
    if kind is not None and (not isinstance(kind, str) or kind not in TYPE_GLOBS):
        raise invalid("type")
    corrections = []
    for key in ("-i", "-n"):
        if key in arguments and type(arguments[key]) is not bool:
            raise invalid(key)
    result = {k: v for k, v in arguments.items() if k in {"path", "pattern", "-i"}}
    for key, default, maximum in (
        ("head_limit", 100, 200),
        ("-A", 0, 5),
        ("-B", 0, 5),
        ("-C", 0, 5),
    ):
        value = arguments.get(key, default)
        if type(value) is not int or value < 0:
            raise invalid(key)
        if value > maximum or (key == "head_limit" and value == 0):
            value = maximum
            corrections.append(f"{key} capped at {maximum}")
        result[key] = value
    if arguments.get("-n") is False:
        corrections.append("-n enabled for source line attribution")
    if len(globs) > 1:
        corrections.append("glob expanded into bounded alternatives")
    if kind is not None:
        corrections.append("type filter applied together with glob")
    return result | {
        "glob": globs,
        "type_globs": TYPE_GLOBS.get(kind, ("*",)),
        "output_mode": mode,
        "-n": True,
        "corrections": corrections,
    }
