"""只清理本同步归属且已失去引用的派生 collection，不删除正文或修订。"""

from app.modules.knowledge.application.ports import GenerationRepository, QdrantPort
from app.modules.knowledge.domain.identity import now


class GenerationRetention:
    def __init__(self, repository: GenerationRepository, qdrant: QdrantPort) -> None:
        self.repository = repository
        self.qdrant = qdrant

    def run(self, *, timestamp: str | None = None) -> dict[str, int]:
        counts = {"checked": 0, "retired": 0, "protected_or_waiting": 0}
        for row in self.repository.candidates():
            with self.repository.source_lock(row["source_id"]):
                # 锁与发布使用同一个平台来源；Qdrant IO 不处于数据库事务内。
                index = self.repository.eligible(row["id"], timestamp or now())
                counts["checked"] += 1
                if index is None:
                    counts["protected_or_waiting"] += 1
                    continue
                self.qdrant.delete_owned(index)
                self.repository.retired(index["id"])
                counts["retired"] += 1
        return counts
