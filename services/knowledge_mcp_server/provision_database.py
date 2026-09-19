"""由运维显式执行的独立数据库账号配置入口，不在 MCP 启动时修改权限。"""

import os
from app.shared.database import Database
from services.knowledge_mcp_server.database_policy import grant_reader


def main() -> int:
    database = None
    try:
        database = Database(os.environ["DATABASE_DSN"])
        grant_reader(database, os.environ["KNOWLEDGE_DATABASE_PASSWORD"])
    except Exception:
        print("KNOWLEDGE_DATABASE_GRANTS_FAILED: 独立角色或权限检查失败")
        return 1
    finally:
        if database is not None:
            database.close()
    print("KNOWLEDGE_DATABASE_GRANTS_SUCCEEDED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
