"""Deterministic answer chunks. Full conditions accompany every returned excerpt."""

from typing import Any

from app.modules.knowledge.domain.chunking import PreparedChunks, _ranges
from app.modules.knowledge.domain.code_configuration import CODE_CHUNK_PROFILE
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import canonical_json, digest


def prepare_code_chunks(record: dict[str, Any]) -> PreparedChunks:
    body = record["body_text"]
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= 64000:
        raise CodeKnowledgeError("CODE_CHUNK_SOURCE_INVALID")
    context = {
        "source_id": record["source_id"],
        "repository_uuid": record["repository_uuid"],
        "branch_path": record["branch_path"],
        "svn_revision": record["svn_revision"],
        "question": record["question_text"],
        "conditions": record["conditions_json"],
        "visibility_scope": record["visibility_scope_json"],
        "claims": record["claims_json"],
        "coverage": record["coverage_json"],
        "unknowns": record["unknowns_json"],
        "support_status": "supported",
    }
    # The embedding prefix is bounded; the authoritative context is never cropped.
    prefix = (
        f"SVN r{record['svn_revision']}\n问题：{record['question_text'][:160]}\n"
        f"适用条件：{canonical_json(record['conditions_json'])}"
    )
    cropped = len(prefix) > CODE_CHUNK_PROFILE.context_chars
    prefix = prefix[: CODE_CHUNK_PROFILE.context_chars - 1] + "…" if cropped else prefix
    chunks: list[dict[str, Any]] = []
    for start, end, flags in _ranges(body, CODE_CHUNK_PROFILE):
        text = body[start:end]
        embedding = prefix + "\n\n" + text
        chunks.append(
            dict(
                ordinal=len(chunks),
                chunk_kind="business_answer",
                source_field="body_text",
                source_start=start,
                source_end=end,
                evidence_text=text,
                embedding_text=embedding,
                char_count=len(text),
                embedding_char_count=len(embedding),
                evidence_hash=digest(text),
                embedding_hash=digest(embedding),
                quality_flags=flags + (["embedding_context_cropped"] if cropped else []),
                context_json=context,
            )
        )
    result = PreparedChunks({"body_text": body}, {"support_status": "supported"}, tuple(chunks))
    validate_code_chunks(result)
    return result


def validate_code_chunks(prepared: PreparedChunks) -> None:
    body, cursor, context = prepared.normalized_fields["body_text"], 0, None
    for ordinal, row in enumerate(prepared.chunks):
        start, end = row["source_start"], row["source_end"]
        current = row["context_json"]
        if (
            row["ordinal"] != ordinal
            or row["chunk_kind"] != "business_answer"
            or row["source_field"] != "body_text"
            or not max(0, cursor - CODE_CHUNK_PROFILE.overlap_chars) <= start < end <= len(body)
            or end <= cursor
            or body[cursor:start].strip()
            or row["evidence_text"] != body[start:end]
            or row["char_count"] != end - start
            or row["char_count"] > CODE_CHUNK_PROFILE.max_chars
            or row["embedding_char_count"] != len(row["embedding_text"])
            or row["embedding_char_count"] > CODE_CHUNK_PROFILE.embedding_chars
            or not row["embedding_text"].endswith(row["evidence_text"])
            or row["evidence_hash"] != digest(row["evidence_text"])
            or row["embedding_hash"] != digest(row["embedding_text"])
            or not isinstance(current, dict)
            or current.get("support_status") != "supported"
            or (context is not None and current != context)
        ):
            raise CodeKnowledgeError("CODE_CHUNK_INTEGRITY_FAILED")
        cursor, context = end, current
    if not prepared.chunks or body[cursor:].strip():
        raise CodeKnowledgeError("CODE_CHUNK_INTEGRITY_FAILED")
