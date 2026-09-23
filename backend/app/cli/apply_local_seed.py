from __future__ import annotations

import os
import re

from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import Database, default_migrations_dir


_SCHEMA_HASH_PLACEHOLDER = re.compile(r"\{\{mcp_tool_schema_hash:([a-z0-9_]+)\}\}")


def local_seed_sql() -> str:
    """Render the local seed with Publication MCP Tool hashes taken from the code manifest."""

    template = (default_migrations_dir().parent / "seeds" / "local_seed.sql").read_text(
        encoding="utf-8"
    )

    def schema_hash(match: re.Match[str]) -> str:
        definition = MCP_TOOL_MANIFEST.get(match.group(1))
        if definition is None:
            raise RuntimeError(f"Local seed references unknown MCP Tool: {match.group(1)}")
        return f"'{definition.schema_hash}'"

    rendered = _SCHEMA_HASH_PLACEHOLDER.sub(schema_hash, template)
    if "{{" in rendered:
        raise RuntimeError("Local seed contains an unresolved placeholder")
    return rendered


def main() -> int:
    database = Database(os.environ["DATABASE_DSN"])
    try:
        database.execute_script(local_seed_sql())
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
