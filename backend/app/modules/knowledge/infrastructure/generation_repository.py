"""向量代际保留事实；保护任意发布/草稿、有效运行及最新两代成功索引。"""

from datetime import datetime, timedelta
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any

from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.infrastructure.storage import source_lock, table
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.shared.database import Database


class GenerationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def t(self, name: str) -> str:
        return table(self.database, name)

    def source_lock(self, source_id: str) -> AbstractContextManager[None]:
        return source_lock(self.database, source_id)

    def candidates(self) -> Iterator[dict[str, Any]]:
        # 按稳定主键分批，受保护版本不能让后续候选永远饥饿。
        cursor = ""
        while True:
            rows = self.database.execute(
                f"select id,source_id from {self.t('vector_index')} where sync_run_id is not null and source_id is not null and state<>'RETIRED' and id>? order by id limit 100",
                (cursor,),
            )
            if not rows:
                return
            yield from rows
            cursor = rows[-1]["id"]

    def _protected(self, index: dict[str, Any]) -> bool:
        if self.database.execute_one(
            f"select 1 as n from {self.t('retrieval_resource')} resource "
            f"join {self.t('retrieval_revision')} revision on revision.id=resource.published_revision_id or revision.id=resource.draft_revision_id "
            "where revision.index_id=? limit 1",
            (index["id"],),
        ):
            return True
        if self.database.execute_one(
            f"select id from {self.t('sync_run')} where source_id=? and active=1 limit 1",
            (index["source_id"],),
        ):
            return True
        run = self.database.execute_one(
            f"select phase,activated_watermark,source_id from {self.t('sync_run')} where id=?",
            (index["sync_run_id"],),
        )
        if (
            not run
            or run["source_id"] != index["source_id"]
            or run["phase"] not in {"ACTIVATED", "CANCELLED"}
        ):
            return True
        if run["phase"] == "ACTIVATED" and not run["activated_watermark"]:
            return True
        protected = self.database.execute(
            f"select i.id from {self.t('vector_index')} i join {self.t('sync_run')} r on r.id=i.sync_run_id "
            "where i.knowledge_base_id=? and r.phase='ACTIVATED' and r.activated_watermark is not null "
            "order by r.activated_watermark desc,i.created_at desc,i.id desc limit 2",
            (index["knowledge_base_id"],),
        )
        return index["id"] in {row["id"] for row in protected}

    def eligible(self, index_id: str, timestamp: str) -> dict[str, Any] | None:
        current_time = datetime.fromisoformat(timestamp)
        if current_time.tzinfo is None:
            raise VectorError("knowledge_vector_retention_clock_invalid")
        with self.database.unit_of_work():
            row = self.database.execute_one(
                f"select code from {self.t('vector_index')} where id=?", (index_id,)
            )
            index = VectorRepository(self.database).get(row["code"]) if row else None
            if not index or not index.get("sync_run_id") or index["state"] == "RETIRED":
                return None
            expected_code = "sync-" + stable_id(
                "sync-index", index["sync_run_id"], index["knowledge_base_id"]
            )
            if index["code"] != expected_code or index["id"] != stable_id(
                "vector-index", expected_code
            ):
                raise VectorError("knowledge_vector_retention_owner_invalid")
            if self._protected(index):
                self.database.execute(
                    f"update {self.t('vector_index')} set unreferenced_at=NULL where id=?",
                    (index_id,),
                )
                return None
            observed = index["unreferenced_at"]
            if observed is None:
                self.database.execute(
                    f"update {self.t('vector_index')} set unreferenced_at=? where id=?",
                    (timestamp, index_id),
                )
                return None
            if isinstance(observed, str):
                observed = datetime.fromisoformat(observed)
            if current_time - observed < timedelta(minutes=10):
                return None
            return index

    def retired(self, index_id: str) -> None:
        with self.database.unit_of_work():
            self.database.execute(
                f"update {self.t('vector_index')} set state='RETIRED',updated_at=? where id=? and sync_run_id is not null",
                (now(), index_id),
            )
