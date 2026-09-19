"""平台桥与 ONES 内部入口共用的固定合同及持久化候选成员检查。"""

from dataclasses import dataclass
from typing import Any

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, checked_identifier
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.domain.models import PinnedKnowledgeResource
from app.modules.knowledge.domain.models import KnowledgeJobAccess


READABILITY_PATH = "/internal/knowledge/work-item-readability"
BRIDGE_PATH = "/api/internal/knowledge/work-item-readability"
MAX_CANDIDATES = 50
MAX_REQUEST_BYTES = 8192


@dataclass(frozen=True)
class ReadabilityRequest:
    knowledge_base_id: str
    resource_revision_id: str
    index_id: str
    chunk_ids: tuple[str, ...]

    @classmethod
    def parse(cls, value: Any) -> "ReadabilityRequest":
        if not isinstance(value, dict) or set(value) != {
            "knowledge_base_id",
            "resource_revision_id",
            "index_id",
            "chunk_ids",
        }:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        chunks = value["chunk_ids"]
        if not isinstance(chunks, list) or not 1 <= len(chunks) <= MAX_CANDIDATES:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        ids = tuple(checked_identifier(item) for item in chunks)
        if len(set(ids)) != len(ids):
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        return cls(
            checked_identifier(value["knowledge_base_id"]),
            checked_identifier(value["resource_revision_id"]),
            checked_identifier(value["index_id"]),
            ids,
        )


def _documents(
    resources: KnowledgeResourceReader, binding: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    ids = tuple(sorted({row["document_id"] for row in evidence.values()}))
    return resources.store.current_documents(binding["source_id"], ids)


@dataclass(frozen=True, repr=False)
class ReadabilityCandidates:
    pin: PinnedKnowledgeResource
    binding: dict[str, Any]
    index: dict[str, Any]
    evidence: dict[str, Any]
    documents: dict[str, Any]

    @classmethod
    def load(
        cls, resources: KnowledgeResourceReader, request: ReadabilityRequest
    ) -> "ReadabilityCandidates":
        pin = resources.resolve(request.knowledge_base_id)
        if pin.revision_id != request.resource_revision_id or pin.index_id != request.index_id:
            raise KnowledgeGovernanceError("knowledge_resource_changed")
        binding = resources.store.get("source_binding", pin.binding_id)
        index = resources.vectors.get(pin.index_code)
        if index is None:
            raise KnowledgeGovernanceError("knowledge_index_unavailable")
        evidence = resources.vectors.evidence_many(index, list(request.chunk_ids))
        if set(evidence) != set(request.chunk_ids):
            raise KnowledgeGovernanceError("knowledge_candidate_invalid")
        return cls(pin, binding, index, evidence, _documents(resources, binding, evidence))

    def recheck(self, resources: KnowledgeResourceReader) -> None:
        resources.recheck(self.pin)
        if (
            resources.vectors.evidence_many(self.index, list(self.evidence)) != self.evidence
            or _documents(resources, self.binding, self.evidence) != self.documents
        ):
            raise KnowledgeGovernanceError("knowledge_candidate_invalid")


def project_readability(
    value: Any,
    request: ReadabilityRequest,
    access: KnowledgeJobAccess,
    candidates: ReadabilityCandidates,
) -> dict[str, Any]:
    expected = {
        "knowledge_base_id": request.knowledge_base_id,
        "resource_revision_id": request.resource_revision_id,
        "index_id": request.index_id,
        "job_id": access.job_id,
        "actor_id": access.actor_id,
    }
    if (
        not isinstance(value, dict)
        or set(value) != {*expected, "items"}
        or any(value[name] != item for name, item in expected.items())
        or not isinstance(value["items"], list)
        or len(value["items"]) != len(request.chunk_ids)
    ):
        raise KnowledgeGovernanceError("knowledge_readability_failed")
    items = []
    per_document: dict[str, Any] = {}
    for chunk_id, item in zip(request.chunk_ids, value["items"], strict=True):
        if (
            not isinstance(item, dict)
            or item.get("chunk_id") != chunk_id
            or type(item.get("readable")) is not bool
        ):
            raise KnowledgeGovernanceError("knowledge_readability_failed")
        document_id = candidates.evidence[chunk_id]["document_id"]
        document = candidates.documents[document_id]
        reference: dict[str, Any] = {"readable": item["readable"]}
        if item["readable"]:
            reference.update(
                {
                    "task_id": document["external_id"],
                    "document_id": document_id,
                    "revision_id": document["current_revision_id"],
                    "source_binding_id": candidates.pin.binding_id,
                }
            )
            if type(item.get("number")) is not int or not 0 < item["number"] < 2**63:
                raise KnowledgeGovernanceError("knowledge_readability_failed")
            reference["number"] = item["number"]
        if item != {"chunk_id": chunk_id, **reference}:
            raise KnowledgeGovernanceError("knowledge_readability_failed")
        if document_id in per_document and per_document[document_id] != reference:
            raise KnowledgeGovernanceError("knowledge_readability_failed")
        per_document[document_id] = reference
        items.append({"chunk_id": chunk_id, **reference})
    return {**expected, "items": items}
