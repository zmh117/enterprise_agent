"""平台到固定 ONES 内部核验入口；沿用完整 scope JWT，只返回安全核验事实。"""

from dataclasses import asdict
import json
from urllib.parse import urlsplit

import httpx

from app.modules.identity.application.principal_jwt import PrincipalTokenIssuer
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.domain.governance import (
    KnowledgeGovernanceError,
    SourceItem,
    checked_identifier,
    strict_object,
)
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.shared.database import Database, assert_external_io_allowed


SOURCE_VERIFICATION_PATH = "/internal/knowledge/source-verification"
DETAIL_TOOL = "ones_get_work_item_detail"


def ones_target_hash(instance_code: str, provider_origin: str) -> str:
    checked_identifier(instance_code)
    origin = provider_origin.strip().rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.path
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise KnowledgeGovernanceError("knowledge_verifier_unavailable")
    return fingerprint({"instance_code": instance_code, "provider_origin": origin})


class OnesSourceVerifier:
    def __init__(
        self,
        database: Database,
        issuer: PrincipalTokenIssuer | None,
        *,
        instance_code: str,
        provider_origin: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.database = database
        self.issuer = issuer
        self.instance_code = checked_identifier(instance_code)
        self.target_hash = ones_target_hash(instance_code, provider_origin)
        self._transport = transport

    def _authorize(self, actor_id: str, job_id: str) -> str:
        if self.issuer is None:
            raise KnowledgeGovernanceError("knowledge_verifier_unavailable")
        job = self.database.execute_one(
            "select j.business_application_id,j.business_application_publication_id from agent_job j "
            "join app_user u on u.id=j.internal_user_id where j.id=? and j.internal_user_id=? "
            "and j.status='RUNNING' and u.status='enabled' and u.account_type='human'",
            (job_id, actor_id),
        )
        if (
            not job
            or not job["business_application_id"]
            or not job["business_application_publication_id"]
        ):
            raise KnowledgeGovernanceError("knowledge_verification_job_invalid")
        verified = self.issuer.snapshot_service.verify(job_id)
        tools = verified["snapshot"].get("tools") or []
        if not any(
            item.get("server_code") == "ones-mcp" and item.get("tool_identifier") == DETAIL_TOOL
            for item in tools
        ):
            raise KnowledgeGovernanceError("knowledge_verification_job_invalid")
        self.issuer.business_authorization_service.require(
            user_id=actor_id,
            application_id=job["business_application_id"],
            tool_identifier=DETAIL_TOOL,
            stage="knowledge_source_verification",
        )
        return str(verified["authorization_hash"])

    def verify(
        self,
        *,
        actor_id: str,
        job_id: str,
        binding_id: str,
        team_id: str,
        items: tuple[SourceItem, ...],
    ) -> bool:
        del team_id  # Team 只能由 ones-mcp 的本人绑定与存储来源决定，不能由 HTTP 调用者覆盖。
        authorization_hash = self._authorize(actor_id, job_id)
        if self.issuer is None:
            raise KnowledgeGovernanceError("knowledge_verifier_unavailable")
        binding = GovernanceStore(self.database).get("source_binding", binding_id)
        # 不缩减 ONES scope；签发器仍签发该 Server 冻结且当前获授权的完整集合。
        token = self.issuer.issue_business_mcp_for_job(job_id=job_id, server_code="ones-mcp")
        try:
            assert_external_io_allowed("knowledge_ones_source_verification")
            with httpx.Client(
                base_url="http://ones-mcp:9104",
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(65, connect=3),
            ) as client:
                with client.stream(
                    "POST",
                    SOURCE_VERIFICATION_PATH,
                    headers={"Authorization": "Bearer " + token},
                    json={"binding_id": binding_id},
                ) as response:
                    if response.status_code != 200:
                        raise KnowledgeGovernanceError("knowledge_verification_failed")
                    raw = bytearray()
                    for part in response.iter_bytes():
                        raw.extend(part)
                        if len(raw) > 8192:
                            raise KnowledgeGovernanceError("knowledge_verification_failed")
            result = json.loads(raw, object_pairs_hook=strict_object)
        except Exception:
            raise KnowledgeGovernanceError("knowledge_verification_failed") from None
        finally:
            token = ""
        if (
            not isinstance(result, dict)
            or set(result)
            != {
                "binding_id",
                "job_id",
                "actor_id",
                "target_hash",
                "corpus_hash",
                "sample_hash",
                "checked_count",
            }
            or result["binding_id"] != binding_id
            or result["job_id"] != job_id
            or result["actor_id"] != actor_id
            or result["target_hash"] != self.target_hash
            or type(result["checked_count"]) is not int
            or result["corpus_hash"] != binding["corpus_hash"]
            or result["checked_count"] != len(items)
            or result["sample_hash"] != fingerprint([asdict(item) for item in items])
        ):
            raise KnowledgeGovernanceError("knowledge_verification_failed")
        if self._authorize(actor_id, job_id) != authorization_hash:
            raise KnowledgeGovernanceError("knowledge_revision_conflict")
        return True
