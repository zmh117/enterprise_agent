#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
EXCLUDED_DIRECTORIES = frozenset(
    {".git", ".venv", "node_modules", "dist", "build", ".pytest_cache"}
)


def _target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0] if value else ""


def check(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for document in sorted(root.rglob("*.md")):
        if any(part in EXCLUDED_DIRECTORIES for part in document.relative_to(root).parts):
            continue
        fenced = False
        fence_marker = ""
        for line_number, line in enumerate(
            document.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            stripped = line.lstrip()
            if stripped.startswith(("```", "~~~")):
                marker = stripped[:3]
                if not fenced:
                    fenced = True
                    fence_marker = marker
                elif marker == fence_marker:
                    fenced = False
                    fence_marker = ""
                continue
            if fenced:
                continue
            for match in LINK.finditer(line):
                raw_target = _target(match.group(1))
                if not raw_target or raw_target.startswith("#"):
                    continue
                parsed = urlsplit(raw_target)
                if parsed.scheme or raw_target.startswith("//"):
                    continue
                decoded_path = unquote(parsed.path)
                if not decoded_path:
                    continue
                candidate = (
                    root / decoded_path.lstrip("/")
                    if decoded_path.startswith("/")
                    else document.parent / decoded_path
                ).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError:
                    errors.append(
                        f"{document.relative_to(root)}:{line_number}: "
                        f"link escapes repository: {raw_target}"
                    )
                    continue
                if not candidate.exists():
                    errors.append(
                        f"{document.relative_to(root)}:{line_number}: missing target: {raw_target}"
                    )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check repository-local Markdown links")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    errors = check(args.root)
    if errors:
        print("MARKDOWN_LINK_CHECK_FAILED")
        print("\n".join(errors))
        return 1
    print("MARKDOWN_LINK_CHECK_SUCCEEDED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
