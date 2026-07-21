from __future__ import annotations

from pathlib import Path
from typing import Any


class SkillLoader:
    DEFAULT_SKILLS = ("bug-analysis", "sql-diagnosis", "redis-diagnosis", "loki-log-analysis")

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd() / ".claude" / "skills"

    def load(self, names: tuple[str, ...] | None = None) -> dict[str, str]:
        result: dict[str, str] = {}
        for name in names or self.DEFAULT_SKILLS:
            path = self.root / name / "SKILL.md"
            if path.exists():
                result[name] = path.read_text()
        return result

    def catalog(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for name in self.DEFAULT_SKILLS:
            path = self.root / name / "SKILL.md"
            try:
                content = path.read_text(encoding="utf-8")
                if not content.strip():
                    raise ValueError("empty skill")
                first_text = next(
                    (
                        line.strip("# ")
                        for line in content.splitlines()
                        if line.strip() and not line.startswith("---")
                    ),
                    name,
                )
                items.append(
                    {
                        "code": name,
                        "name": first_text[:120] or name,
                        "description": _description(content),
                        "source": "managed-filesystem",
                        "status": "loaded",
                        "assignable": True,
                        "error_summary": "",
                    }
                )
            except Exception:
                items.append(
                    {
                        "code": name,
                        "name": name,
                        "description": "",
                        "source": "managed-filesystem",
                        "status": "unavailable",
                        "assignable": False,
                        "error_summary": "Skill could not be loaded",
                    }
                )
        return items


def _description(content: str) -> str:
    for line in content.splitlines():
        text = line.strip()
        if text and not text.startswith(("#", "---", "name:")):
            return text[:300]
    return ""
