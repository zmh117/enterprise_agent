from __future__ import annotations

from pathlib import Path


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
