"""知识读取上下文与固定资源引用；不含凭据或正文。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeJobAccess:
    job_id: str
    actor_id: str
    application_id: str
    application_publication_id: str
    snapshot_hash: str
    authorization_hash: str
    knowledge_base_ids: tuple[str, ...]
    current_authorization_hash: str


@dataclass(frozen=True)
class OnesKnowledgeIdentity:
    identity_id: str
    subject_id: str
    instance_code: str
    team_id: str


@dataclass(frozen=True)
class PinnedKnowledgeResource:
    knowledge_base_id: str
    resource_id: str
    revision_id: str
    binding_id: str
    index_id: str
    index_code: str
    fingerprint: str
