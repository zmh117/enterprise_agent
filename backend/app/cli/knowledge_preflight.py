"""固定知识依赖预检；只输出固定退出码，不输出连接配置。"""

import os
import sys
import httpx
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator


def main() -> int:
    database = None
    try:
        database = Database(os.environ["DATABASE_DSN"])
        SchemaHeadValidator(database, default_migrations_dir()).require_current()
        if sys.argv[1:] == ["ready"]:
            with httpx.Client(trust_env=False, timeout=5) as client:
                for url in (
                    "http://knowledge-qdrant:6333/readyz",
                    "http://knowledge-embedding:8096/ready",
                    "http://knowledge-embedding-online:8096/ready",
                    "http://knowledge-reranker:8097/ready",
                    "http://knowledge-mcp:9108/health",
                ):
                    if client.get(url).status_code != 200:
                        return 1
        elif sys.argv[1:] != ["schema"]:
            return 2
        return 0
    except Exception:
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
