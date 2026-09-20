"""只建立知识内容连接，不替换授权/Job/审计使用的平台数据库。"""

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from urllib.parse import quote, urlencode

from app.modules.knowledge.application.content_access import KnowledgeContent
from app.modules.knowledge.application.retrieval_budget import io_timeout
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.storage_connection import storage_config
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.infrastructure.vector_clients import QdrantClient
from app.shared.database import Database, assert_external_io_allowed


class PlatformStorageCredentials:
    """仅在已有平台密钥的 API/ONES 进程装配，不导出通用 Secret 读取接口。"""

    def __init__(self, resolve: Callable[[str], str]) -> None:
        self._resolve = resolve

    def __call__(self, config: dict[str, Any], base_id: str, revision_id: str) -> dict[str, str]:
        checked = storage_config(config)
        assert checked is not None
        try:
            result = {}
            pg = checked["postgres"]
            if pg["mode"] == "external":
                result["postgres_password"] = self._resolve(pg["password_ref"])
            if checked["qdrant"]["api_key_ref"]:
                result["qdrant_api_key"] = self._resolve(checked["qdrant"]["api_key_ref"])
            if any(not isinstance(v, str) or not 1 <= len(v) <= 8192 for v in result.values()):
                raise ValueError
            return result
        except Exception:
            raise KnowledgeGovernanceError("knowledge_storage_credentials_unavailable") from None


class ManagedContentAccess:
    def __init__(
        self,
        platform_database: Database,
        credentials: Callable[[dict[str, Any], str, str], dict[str, str]],
        *,
        database_factory: Callable[..., Database] = Database,
        qdrant_factory: Callable[..., QdrantClient] = QdrantClient,
    ) -> None:
        self.platform_database = platform_database
        self.credentials = credentials
        self.database_factory = database_factory
        self.qdrant_factory = qdrant_factory

    @contextmanager
    def open(
        self, config: dict[str, Any] | None, *, knowledge_base_id: str, revision_id: str
    ) -> Iterator[KnowledgeContent]:
        checked = storage_config(config)
        with ExitStack() as cleanup:
            if checked is None:
                yield KnowledgeContent(
                    GovernanceStore(self.platform_database),
                    VectorRepository(self.platform_database),
                )
                return
            try:
                assert_external_io_allowed("knowledge_content_connection")
                secrets = self.credentials(checked, knowledge_base_id, revision_id)
                database = self.platform_database
                pg = checked["postgres"]
                if pg["mode"] == "external":
                    timeout = max(1, int(io_timeout(5)))
                    host = f"[{pg['host']}]" if ":" in pg["host"] else pg["host"]
                    options = urlencode(
                        {
                            "sslmode": pg["sslmode"],
                            "connect_timeout": timeout,
                            "options": "-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=3000",
                        },
                        quote_via=quote,
                    )
                    dsn = (
                        f"postgresql://{quote(pg['username'], safe='')}:{quote(secrets['postgres_password'], safe='')}"
                        f"@{host}:{pg['port']}/{quote(pg['database'], safe='')}?{options}"
                    )
                    database = self.database_factory(
                        dsn, pool_min_size=0, pool_max_size=1, pool_timeout_seconds=3
                    )
                    cleanup.callback(database.close)
                    # 内容账号可以是管理员或读写账号；当前读取用途仍须使用只读会话。
                    # 不改变账号权限，也不对内容库执行平台 schema-head 校验或自动建表。
                    session = database.execute_one(
                        "select current_setting('transaction_read_only') as read_only"
                    )
                    if not session or session["read_only"] != "on":
                        raise KnowledgeGovernanceError("knowledge_storage_readonly_unavailable")
                qdrant = self.qdrant_factory(
                    endpoint=checked["qdrant"]["url"], api_key=secrets.get("qdrant_api_key", "")
                )
                cleanup.callback(qdrant.http.close)
                handle = KnowledgeContent(
                    GovernanceStore(database), VectorRepository(database), qdrant
                )
            except KnowledgeGovernanceError:
                raise
            except Exception:
                raise KnowledgeGovernanceError("knowledge_storage_unavailable") from None
            try:
                yield handle
            except KnowledgeGovernanceError:
                raise
            except Exception:
                raise KnowledgeGovernanceError("knowledge_storage_unavailable") from None
