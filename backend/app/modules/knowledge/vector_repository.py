"""版本化语料和索引检查点；不持久化向量，不执行外部 IO。"""

from collections.abc import Iterator
import hashlib
import json
from typing import Any
import uuid

from app.modules.knowledge.ones_export import identifier
from app.modules.knowledge.storage import insert, now, stable_id, table
from app.modules.knowledge.vector_contract import VectorError, fingerprint, profile
from app.shared.database import Database


class VectorRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def t(self, name: str) -> str:
        return table(self.database, name)

    def scope(self, code: str) -> str:
        identifier(code)
        row = self.database.execute_one(f"select id,state from {self.t('knowledge_base')} where code=?", (code,))
        if not row or row['state'] != 'storage_only':
            raise VectorError('knowledge_vector_base_unavailable')
        return str(row['id'])

    def _query(self, *, indexed: bool = False) -> str:
        checkpoint_join = (f"join {self.t('vector_index_item')} i on i.chunk_id=c.id and i.index_id=? "
                           "and i.state='INDEXED' and i.embedding_text_hash=c.embedding_hash " if indexed else '')
        return (
            f"from {self.t('document_chunk')} c join {self.t('document_chunk_set')} s on s.id=c.chunk_set_id "
            f"join {self.t('document')} d on d.id=s.document_id and d.current_revision_id=s.document_revision_id "
            f"join {self.t('document_revision')} r on r.id=s.document_revision_id and r.document_id=d.id "
            f"join {self.t('knowledge_base_document')} m on m.document_id=d.id "
            f"join {self.t('knowledge_base')} k on k.id=m.knowledge_base_id "
            + checkpoint_join +
            "where m.knowledge_base_id=? and s.profile_hash=? and m.state='included' "
            "and d.lifecycle_state='active' and k.state='storage_only' "
        )

    def rows(self, base_id: str, chunk_profile: str) -> Iterator[dict[str, Any]]:
        cursor = ''
        while True:
            rows = self.database.execute(
                "select c.*,s.document_id,s.document_revision_id,s.profile_hash as chunk_profile_hash,"
                "s.source_content_hash,s.chunk_count,r.content_hash,d.document_kind " + self._query() +
                "and c.id>? order by c.id limit 32", (base_id, chunk_profile, cursor),
            )
            if not rows:
                return
            for row in rows:
                if (row['document_kind'] != 'defect' or row['source_content_hash'] != row['content_hash']
                        or fingerprint(row['embedding_text']) != row['embedding_hash']
                        or fingerprint(row['evidence_text']) != row['evidence_hash']):
                    raise VectorError('knowledge_vector_source_invalid')
                yield row
            cursor = rows[-1]['id']

    @staticmethod
    def identity(row: dict[str, Any]) -> str:
        return fingerprint([row[k] for k in ('id', 'document_id', 'document_revision_id',
                                             'chunk_profile_hash', 'content_hash', 'embedding_hash', 'evidence_hash')])

    def snapshot(self, base_id: str, chunk_profile: str, documents: int, chunks: int) -> dict[str, Any]:
        if not 1 <= documents <= 200_000 or not documents <= chunks <= 2_000_000 or len(chunk_profile) != 64:
            raise VectorError('knowledge_vector_expected_count_invalid')
        count = self.database.execute_one(
            f"select count(*) as n from {self.t('knowledge_base_document')} m "
            f"join {self.t('document')} d on d.id=m.document_id "
            "where m.knowledge_base_id=? and m.state='included' and d.lifecycle_state='active'", (base_id,),
        )
        if not count or count['n'] != documents:
            raise VectorError('knowledge_vector_count_mismatch')
        digest = hashlib.sha256()
        sets: dict[str, tuple[int, int]] = {}
        seen_documents: set[str] = set()
        total = 0
        for row in self.rows(base_id, chunk_profile):
            digest.update(self.identity(row).encode())
            actual, expected = sets.get(row['chunk_set_id'], (0, row['chunk_count']))
            sets[row['chunk_set_id']] = (actual + 1, expected)
            seen_documents.add(row['document_id'])
            total += 1
        if (total != chunks or len(seen_documents) != documents or len(sets) != documents
                or any(actual != expected for actual, expected in sets.values())):
            raise VectorError('knowledge_vector_count_mismatch')
        return {'knowledge_base_id': base_id, 'chunk_profile_hash': chunk_profile, 'corpus_hash': digest.hexdigest(),
                'expected_document_count': documents, 'expected_chunk_count': chunks}

    def assert_current(self, index: dict[str, Any]) -> None:
        current = self.snapshot(index['knowledge_base_id'], index['chunk_profile_hash'],
                                index['expected_document_count'], index['expected_chunk_count'])
        if any(index[k] != v for k, v in current.items()):
            raise VectorError('knowledge_vector_source_changed')

    def get(self, code: str) -> dict[str, Any] | None:
        identifier(code)
        row = self.database.execute_one(f"select * from {self.t('vector_index')} where code=?", (code,))
        if row and isinstance(row['profile'], str):
            row['profile'] = json.loads(row['profile'])
        return row

    def create(self, code: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        identifier(code)
        index_id = stable_id('vector-index', code)
        values = {'id': index_id, 'code': code, **snapshot, 'profile': profile(),
                  'profile_hash': fingerprint(profile()), 'collection_name': 'knowledge_' + uuid.UUID(index_id).hex}
        with self.database.unit_of_work():
            found = self.get(code)
            if found:
                if any(found[k] != v for k, v in values.items()):
                    raise VectorError('knowledge_vector_index_conflict')
                return found
            insert(self.database, 'vector_index', {**values, 'state': 'BUILDING', 'error_code': None,
                                                   'created_at': now(), 'updated_at': now()})
        return {**values, 'state': 'BUILDING'}

    def manifest(self, index: dict[str, Any]) -> None:
        # 每页短事务；中断后补齐。全部完成前不接触 Qdrant。
        for batch in batches(self.rows(index['knowledge_base_id'], index['chunk_profile_hash']), 32):
            with self.database.unit_of_work():
                for row in batch:
                    values = {'index_id': index['id'], 'chunk_id': row['id'], 'point_id': point_id(index, row),
                              'embedding_text_hash': row['embedding_hash']}
                    insert(self.database, 'vector_index_item', {**values, 'state': 'PENDING', 'attempt_count': 0,
                           'error_code': None, 'created_at': now(), 'updated_at': now()},
                           conflict='on conflict(index_id,chunk_id) do nothing')
                    stored = self.database.execute_one(
                        f"select * from {self.t('vector_index_item')} where index_id=? and chunk_id=?",
                        (index['id'], row['id']),
                    )
                    if not stored or any(stored[k] != v for k, v in values.items()):
                        raise VectorError('knowledge_vector_manifest_conflict')
        count = self.database.execute_one(f"select count(*) as n from {self.t('vector_index_item')} where index_id=?",
                                          (index['id'],))
        if not count or count['n'] != index['expected_chunk_count']:
            raise VectorError('knowledge_vector_manifest_conflict')
        self.assert_current(index)

    def state(self, index: dict[str, Any], state: str, error: str | None = None) -> None:
        with self.database.unit_of_work():
            self.database.execute(f"update {self.t('vector_index')} set state=?,error_code=?,updated_at=? where id=?",
                                  (state, error, now(), index['id']))
        index['state'] = state

    def checkpoint(self, index: dict[str, Any], rows: list[dict[str, Any]], state: str,
                   *, error: str | None = None, attempted: bool = False) -> None:
        with self.database.unit_of_work():
            for row in rows:
                self.database.execute(
                    f"update {self.t('vector_index_item')} set state=?,error_code=?,updated_at=?,"
                    "attempt_count=attempt_count+? where index_id=? and chunk_id=?",
                    (state, error, now(), int(attempted), index['id'], row['id']),
                )

    def evidence_many(self, index: dict[str, Any], chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not chunk_ids:
            return {}
        if len(chunk_ids) > 200:
            raise VectorError('knowledge_vector_batch_invalid')
        # 一个数据库语句读取整个候选批次，避免逐点 N+1 及候选间不同的语句快照。
        rows = self.database.execute(
            "select c.*,s.document_id,s.document_revision_id,s.source_content_hash,r.content_hash,i.point_id " +
            self._query(indexed=True) + f"and c.id in ({','.join('?' for _ in chunk_ids)})",
            (index['id'], index['knowledge_base_id'], index['chunk_profile_hash'], *chunk_ids),
        )
        return {row['id']: row for row in rows if row['source_content_hash'] == row['content_hash']
                and fingerprint(row['embedding_text']) == row['embedding_hash']
                and fingerprint(row['evidence_text']) == row['evidence_hash']
                and row['point_id'] == point_id(index, row)}


def batches(rows: Iterator[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def point_id(index: dict[str, Any], row: dict[str, Any]) -> str:
    return str(uuid.uuid5(uuid.UUID(index['id']), row['id']))


def payload(index: dict[str, Any], row: dict[str, Any]) -> dict[str, str]:
    return {'index_id': index['id'], 'knowledge_base_id': index['knowledge_base_id'],
            'document_id': row['document_id'], 'revision_id': row['document_revision_id'], 'chunk_id': row['id'],
            'profile_hash': index['profile_hash'], 'embedding_hash': row['embedding_hash'], 'chunk_kind': row['chunk_kind']}
