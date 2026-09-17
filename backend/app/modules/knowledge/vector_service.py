"""显式本机索引和查询编排；外部 IO 始终在数据库事务之外。"""

from collections.abc import Callable, Iterator
import math
import time
from typing import Any

from app.modules.knowledge.storage import source_lock
from app.modules.knowledge.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.vector_contract import MAX_BATCH_TOKENS, VectorError, fingerprint, profile
from app.modules.knowledge.vector_repository import VectorRepository, batches, payload, point_id
from app.shared.database import Database


class VectorService:
    def __init__(self, database: Database, embedding: EmbeddingClient, qdrant: QdrantClient) -> None:
        self.repository = VectorRepository(database)
        self.embedding = embedding
        self.qdrant = qdrant

    def grouped(self, rows: Iterator[dict[str, Any]]) -> Iterator[tuple[list[dict[str, Any]], list[int]]]:
        for window in batches(rows, 8):
            counts = self.embedding.call([r['embedding_text'] for r in window])['token_counts']
            group: list[dict[str, Any]] = []
            tokens: list[int] = []
            for row, count in zip(window, counts, strict=True):
                if tokens and sum(tokens) + count > MAX_BATCH_TOKENS:
                    yield group, tokens
                    group, tokens = [], []
                group.append(row)
                tokens.append(count)
            if group:
                yield group, tokens

    def preflight(self, snapshot: dict[str, Any], *, benchmark: bool = False) -> dict[str, Any]:
        self.embedding.check()
        repo = self.repository
        lengths: list[tuple[int, str]] = []
        tokens: list[int] = []
        for rows, counts in self.grouped(repo.rows(snapshot['knowledge_base_id'], snapshot['chunk_profile_hash'])):
            lengths.extend((r['embedding_char_count'], r['id']) for r in rows)
            tokens.extend(counts)
        repo.assert_current(snapshot)
        if len(tokens) != snapshot['expected_chunk_count']:
            raise VectorError('knowledge_vector_source_changed')
        ordered = sorted(tokens)
        result: dict[str, Any] = {'mode': 'benchmark' if benchmark else 'preflight', **snapshot,
            'profile_hash': self.embedding.profile_hash, 'token_counts': {'total': sum(tokens), 'min': min(tokens),
            'max': max(tokens), 'p50': ordered[len(ordered)//2], 'p95': ordered[int(len(ordered)*.95)]}}
        if benchmark:
            # 按长度排序后等距分层；选点固定，不打印实际文本。
            lengths.sort()
            sample_count = min(100, len(lengths))
            selected = {lengths[round(i * (len(lengths) - 1) / max(1, sample_count - 1))][1] for i in range(sample_count)}
            sample = (r for r in repo.rows(snapshot['knowledge_base_id'], snapshot['chunk_profile_hash']) if r['id'] in selected)
            started = time.monotonic()
            latencies: list[float] = []
            for rows, counts in self.grouped(sample):
                tick = time.monotonic()
                value = self.embedding.call([r['embedding_text'] for r in rows], encode=True)
                if value['token_counts'] != counts:
                    raise VectorError('knowledge_embedding_result_invalid')
                latencies.append(time.monotonic() - tick)
            elapsed = time.monotonic() - started
            repo.assert_current(snapshot)
            result['benchmark'] = {'chunks': sample_count, 'seconds': round(elapsed, 3),
                'chunks_per_second': round(sample_count / max(elapsed, .001), 3),
                'batch_seconds_max': round(max(latencies), 3),
                'estimated_full_seconds': round(elapsed / sample_count * len(tokens))}
        return result

    def _verify_points(self, index: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        points = self.qdrant.retrieve(index, [point_id(index, r) for r in rows])
        missing = []
        for row in rows:
            found = points.get(point_id(index, row))
            if found is None:
                missing.append(row)
            elif found.get('payload') != payload(index, row):
                raise VectorError('knowledge_vector_point_conflict')
        return missing

    def build(self, code: str, snapshot: dict[str, Any], *,
              progress: Callable[[dict[str, int]], None] | None = None) -> dict[str, Any]:
        repo = self.repository
        self.embedding.check()
        with source_lock(repo.database, 'vector-index:' + code):
            index = repo.create(code, snapshot)
            repo.state(index, 'BUILDING')
            processed, encoded, reused = 0, 0, 0
            started = time.monotonic()
            try:
                repo.manifest(index)
                self.qdrant.ensure(index)
                for rows in batches(repo.rows(index['knowledge_base_id'], index['chunk_profile_hash']), 32):
                    missing = self._verify_points(index, rows)
                    reused += len(rows) - len(missing)
                    for group, counts in self.grouped(iter(missing)):
                        repo.checkpoint(index, group, 'PENDING', attempted=True)
                        try:
                            result = self.embedding.call([r['embedding_text'] for r in group], encode=True)
                            if result['token_counts'] != counts:
                                raise VectorError('knowledge_embedding_result_invalid')
                            self.qdrant.upsert(index, [{'id': point_id(index, row), 'payload': payload(index, row),
                                'vector': vector} for row, vector in zip(group, result['vectors'], strict=True)])
                            repo.checkpoint(index, group, 'INDEXED')
                            encoded += len(group)
                        except Exception:
                            repo.checkpoint(index, group, 'FAILED', error='knowledge_vector_batch_failed')
                            raise
                    repo.checkpoint(index, rows, 'INDEXED')
                    processed += len(rows)
                    if progress:
                        progress({'processed': processed, 'total': index['expected_chunk_count'],
                                  'encoded': encoded, 'reused': reused})
                # 逐项核验包括已记账项；总数相同并不足以证明正确。
                verified = 0
                for rows in batches(repo.rows(index['knowledge_base_id'], index['chunk_profile_hash']), 32):
                    if self._verify_points(index, rows):
                        raise VectorError('knowledge_vector_points_missing')
                    verified += len(rows)
                if verified != index['expected_chunk_count'] or self.qdrant.count(index) != verified:
                    raise VectorError('knowledge_vector_count_mismatch')
                repo.assert_current(index)
                repo.state(index, 'READY')
                return {'mode': 'commit', 'index_id': index['id'], 'state': 'READY', 'verified': verified,
                        'encoded': encoded, 'reused': reused, 'seconds': round(time.monotonic()-started, 3),
                        'corpus_hash': index['corpus_hash'], 'profile_hash': index['profile_hash']}
            except Exception as exc:
                code = exc.code if isinstance(exc, VectorError) else 'knowledge_vector_build_failed'
                repo.state(index, 'FAILED', code)
                raise VectorError(code) from None

    def query(self, code: str, base_code: str, query: str, *, top_k: int = 10) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000 or type(top_k) is not int or not 1 <= top_k <= 20:
            raise VectorError('knowledge_vector_query_invalid')
        repo = self.repository
        index = repo.get(code)
        if (not index or index['state'] != 'READY' or index['knowledge_base_id'] != repo.scope(base_code)
                or index['profile'] != profile() or index['profile_hash'] != fingerprint(profile())):
            raise VectorError('knowledge_vector_index_not_ready')
        self.embedding.check()
        self.qdrant.check(index)
        vector = self.embedding.call([query], encode=True)['vectors'][0]
        limit = min(200, max(20, top_k * 4))
        docs: dict[str, dict[str, Any]] = {}
        candidates = []
        while True:
            candidates = self.qdrant.search(index, vector, limit)
            docs = {}
            seen: set[str] = set()
            for hit in candidates:
                if (not isinstance(hit, dict) or not isinstance(hit.get('id'), str) or hit['id'] in seen
                        or type(hit.get('score')) not in (float, int) or not math.isfinite(hit['score'])
                        or not isinstance(hit.get('payload'), dict)):
                    raise VectorError('knowledge_vector_response_invalid')
                seen.add(hit['id'])
                chunk_id = hit['payload'].get('chunk_id')
                if not isinstance(chunk_id, str):
                    raise VectorError('knowledge_vector_response_invalid')
            current = repo.evidence_many(index, [hit['payload']['chunk_id'] for hit in candidates])
            for hit in candidates:
                row = current.get(hit['payload']['chunk_id'])
                if row is None:
                    continue
                if hit['id'] != point_id(index, row) or hit['payload'] != payload(index, row):
                    raise VectorError('knowledge_vector_point_conflict')
                evidence = {k: row[k] for k in ('source_field', 'source_start', 'source_end', 'chunk_kind', 'evidence_hash')}
                evidence.update({'chunk_id': row['id'], 'score': hit['score']})
                doc = docs.setdefault(row['document_id'], {'document_id': row['document_id'],
                    'revision_id': row['document_revision_id'], 'score': hit['score'], 'evidence': []})
                doc['score'] = max(doc['score'], hit['score'])
                doc['evidence'].append(evidence)
            if len(docs) >= top_k or len(candidates) < limit or limit == 200:
                break
            limit = min(200, limit * 2)
        for doc in docs.values():
            doc['evidence'] = sorted(doc['evidence'], key=lambda e: (-e['score'], e['chunk_id']))[:3]
        final_index = repo.get(code)
        if not final_index or final_index['state'] != 'READY':
            raise VectorError('knowledge_vector_index_not_ready')
        results = sorted(docs.values(), key=lambda d: (-d['score'], d['document_id']))[:top_k]
        return {'index_id': index['id'], 'documents': results, 'partial': len(results) < top_k,
                'candidates': len(candidates), 'candidate_limit': limit,
                'bounded': limit == 200 and len(candidates) == 200}
