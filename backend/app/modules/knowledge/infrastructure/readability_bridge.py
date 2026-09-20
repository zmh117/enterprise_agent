"""双身份平台桥：固定只读用途，ONES Principal 仅在本地调用栈中存在。"""

from dataclasses import asdict
import json
from typing import Any

import httpx

from app.modules.identity.application.principal_jwt import (
    PrincipalTokenIssuer,
    PrincipalTokenVerifier,
)
from app.modules.identity.application.service_principal import KnowledgeServicePrincipalVerifier
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, strict_object
from app.modules.knowledge.domain.models import KnowledgeJobAccess
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate
from app.modules.knowledge.application.readability import (
    READABILITY_PATH,
    ReadabilityCandidates,
    ReadabilityRequest,
)
from app.modules.knowledge.application.retrieval_budget import RetrievalBudget, current_budget
from app.modules.knowledge.infrastructure.reader_access import job_budget
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.shared.database import assert_external_io_allowed
from app.shared.bounded_read_http import request_bytes
from app.shared.ones_io_budget import ones_io_timeout


class PlatformOnesReadabilityGateway:
    def __init__(
        self,
        service_identity: KnowledgeServicePrincipalVerifier,
        principal: PrincipalTokenVerifier,
        issuer: PrincipalTokenIssuer,
        gate: KnowledgeJobGate,
        *,
        instance_code: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if principal.expected_audience != "knowledge-mcp":
            raise ValueError("Knowledge bridge requires its own Business Principal audience")
        self.service_identity = service_identity
        self.principal = principal
        self.issuer = issuer
        self.gate = gate
        self.instance_code = instance_code
        self._transport = transport

    def authenticate(self, service_token: str, knowledge_token: str) -> KnowledgeJobAccess:
        self.service_identity.verify(service_token)
        claims = self.principal.verify_for_running_job(
            knowledge_token,
            self.gate.database,
            self.gate.snapshots,
            required_scope="mcp:knowledge-mcp:knowledge_search:invoke",
        )
        return self.gate.resolve(job_id=claims["job_id"], actor_id=claims["sub"])

    def budget(self, job_id: str, *, deadline_ms: int | None = None) -> RetrievalBudget:
        return job_budget(self.gate.database, job_id, deadline_ms=deadline_ms)

    def identity_fingerprint(self, actor_id: str, candidates: ReadabilityCandidates) -> str:
        # 只读取身份与凭据状态，不读取/解密任何凭据。Provider 访问仍完全由 ONES MCP 负责。
        rows = self.gate.database.execute(
            "select i.id,i.external_subject_id,i.tenant_code,i.metadata_json,c.id as credential_id "
            "from user_external_identity i left join external_identity_credential c "
            "on c.external_identity_id=i.id and c.provider='ones' and c.status='ACTIVE' "
            "where i.user_id=? and i.provider='ones' and i.status='enabled' order by i.id",
            (actor_id,),
        )
        if len(rows) != 1:
            raise KnowledgeGovernanceError("knowledge_authorization_changed")
        row = rows[0]
        try:
            metadata = json.loads(row["metadata_json"], object_pairs_hook=strict_object)
            teams = metadata["team_uuids"]
            default = metadata["default_team_id"]
            if (
                not isinstance(teams, list)
                or not isinstance(default, str)
                or not default
                or teams.count(default) != 1
                or row["tenant_code"] != self.instance_code
                or not row["external_subject_id"]
                or not row["credential_id"]
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError, RecursionError):
            raise KnowledgeGovernanceError("knowledge_authorization_changed") from None
        return fingerprint(
            {
                "identity_id": row["id"],
                "subject": row["external_subject_id"],
                "instance": row["tenant_code"],
                "team": default,
                "credential_id": row["credential_id"],
            }
        )

    def request_ones(self, job_id: str, request: ReadabilityRequest) -> Any:
        token = self.issuer.issue_business_mcp_for_job(job_id=job_id, server_code="ones-mcp")
        try:
            assert_external_io_allowed("knowledge_ones_readability")
            if self._transport is None:
                status, body = request_bytes(
                    "POST",
                    "http://ones-mcp:9104" + READABILITY_PATH,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/json",
                        **self._deadline_headers(),
                    },
                    content=json.dumps(asdict(request)).encode(),
                    timeout=ones_io_timeout(120),
                    max_bytes=64 * 1024,
                )
                ones_io_timeout(120)
                if status != 200:
                    raise ValueError
                return json.loads(body, object_pairs_hook=strict_object)
            with httpx.Client(
                base_url="http://ones-mcp:9104",
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(ones_io_timeout(120), connect=ones_io_timeout(3)),
            ) as client:
                with client.stream(
                    "POST",
                    READABILITY_PATH,
                    headers={"Authorization": "Bearer " + token, **self._deadline_headers()},
                    json=asdict(request),
                ) as response:
                    if response.status_code != 200:
                        raise ValueError
                    raw = bytearray()
                    for part in response.iter_bytes():
                        ones_io_timeout(120)
                        raw.extend(part)
                        if len(raw) > 64 * 1024:
                            raise ValueError
            return json.loads(raw, object_pairs_hook=strict_object)
        except Exception:
            # 不记录 HTTP 异常、响应或 Token；Provider 故障不能降级为不可读/零命中。
            raise KnowledgeGovernanceError("knowledge_readability_failed") from None
        finally:
            token = ""

    @staticmethod
    def _deadline_headers() -> dict[str, str]:
        budget = current_budget()
        if budget is None:
            raise KnowledgeGovernanceError("knowledge_search_budget_exhausted")
        return budget.headers()
