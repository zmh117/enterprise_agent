from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any


class SkillLoader:
    DEFAULT_SKILLS = (
        "bug-analysis",
        "sql-diagnosis",
        "redis-diagnosis",
        "loki-log-analysis",
        "ones-query",
    )
    MANAGED_SKILLS = DEFAULT_SKILLS + ("code-business-query",)
    VERSIONED_SKILLS = frozenset({"code-business-query"})

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd() / ".claude" / "skills"

    def load(self, names: tuple[str, ...] | None = None) -> dict[str, str]:
        result: dict[str, str] = {}
        selected = self.DEFAULT_SKILLS if names is None else names
        for name in selected:
            path = self.root / name / "SKILL.md"
            if path.exists():
                result[name] = path.read_text()
        return result

    def freeze_versioned(self, names: tuple[str, ...]) -> dict[str, dict[str, str]]:
        selected = tuple(name for name in names if name in self.VERSIONED_SKILLS)
        content = self.load(selected)
        if set(content) != set(selected) or any(not text.strip() for text in content.values()):
            raise ValueError("Versioned skill is unavailable")
        return {
            name: {"content": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
            for name, text in content.items()
        }

    def load_publication(self, snapshot: dict[str, Any]) -> dict[str, str]:
        names = tuple(str(item) for item in snapshot.get("skills") or [])
        result = self.load(tuple(name for name in names if name not in self.VERSIONED_SKILLS))
        frozen = snapshot.get("versioned_skills") or {}
        if set(frozen) != set(names) & self.VERSIONED_SKILLS:
            raise ValueError("Versioned skill binding is invalid")
        for name, binding in frozen.items():
            content = binding.get("content")
            if not isinstance(content, str) or hashlib.sha256(
                content.encode()
            ).hexdigest() != binding.get("sha256"):
                raise ValueError("Versioned skill digest is invalid")
            result[name] = content
        return result

    def catalog(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for name in self.MANAGED_SKILLS:
            path = self.root / name / "SKILL.md"
            try:
                content = path.read_text(encoding="utf-8")
                if not content.strip():
                    raise ValueError("empty skill")
                first_text = next(
                    (
                        line.strip("# ")
                        for line in content.splitlines()
                        if line.strip()
                        and not line.strip().startswith(("---", "name:", "description:"))
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
        if text.startswith("description:"):
            return text.removeprefix("description:").strip()[:300]
        if text and not text.startswith(("#", "---", "name:")):
            return text[:300]
    return ""
