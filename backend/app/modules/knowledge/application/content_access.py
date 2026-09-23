"""治理数据与内容数据的独立读取边界；连接创建和关闭归基础设施。"""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.knowledge.application.ports import VectorRepository, QdrantPort
from app.modules.knowledge.domain.governance import SourceItem


class ContentRepository(Protocol):
    """内容侧只读合同；不包含资源发布、平台授权、事务或任何写入。"""

    def get(self, name: str, identifier: str) -> dict[str, Any]: ...
    def members(self, base_id: str) -> list[dict[str, Any]]: ...
    def source_items(self, source_id: str) -> tuple[SourceItem, ...]: ...
    def member_source_items(self, base_id: str, source_id: str) -> tuple[SourceItem, ...]: ...
    @staticmethod
    def source_hash(items: tuple[SourceItem, ...]) -> str: ...
    def current_documents(self, source_id: str, ids: tuple[str, ...]) -> dict[str, Any]: ...
    def catalog(self) -> dict[str, Any]: ...


@dataclass(frozen=True, repr=False)
class KnowledgeContent:
    records: ContentRepository
    vectors: VectorRepository
    qdrant: QdrantPort | None = None


class ContentAccess(Protocol):
    def open(
        self, config: dict[str, Any] | None, *, knowledge_base_id: str, revision_id: str
    ) -> AbstractContextManager[KnowledgeContent]: ...
