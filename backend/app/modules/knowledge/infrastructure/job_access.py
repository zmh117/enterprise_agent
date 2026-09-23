"""知识调用的持久化 Job 边界；不签发身份、不执行 Provider 或模型请求。"""

import json

from app.modules.authorization_center.application.service import BusinessAuthorizationService
from app.modules.agent_config.application.service import agent_config_hash
from app.modules.agent_config.infrastructure.repository import AgentConfigRepository
from app.modules.business_application.domain.policies import verify_publication_snapshot
from app.modules.knowledge.domain.governance import (
    KnowledgeGovernanceError,
    strict_object,
    checked_identifier,
)
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.shared.database import Database
from app.modules.knowledge.domain.models import KnowledgeJobAccess


KNOWLEDGE_TOOLS = ("knowledge_list_bases", "knowledge_search")
KNOWLEDGE_SERVER = "knowledge-mcp"
DETAIL_TOOL = "ones_get_work_item_detail"


class KnowledgeJobGate:
    def __init__(
        self,
        database: Database,
        snapshots: JobMcpToolSnapshotService,
        authorization: BusinessAuthorizationService,
    ) -> None:
        self.database = database
        self.snapshots = snapshots
        self.authorization = authorization

    def check_before_model(self, job_id: str, actor_id: str) -> None:
        from app.modules.knowledge.domain.tool_policy import uses_knowledge_tools

        frozen_tools = self.snapshots.verify(job_id)["snapshot"]["tools"]
        if uses_knowledge_tools(frozen_tools):
            self.resolve(job_id=job_id, actor_id=actor_id)

    @staticmethod
    def _invalid() -> KnowledgeGovernanceError:
        return KnowledgeGovernanceError("knowledge_job_denied")

    def resolve(self, *, job_id: str, actor_id: str) -> KnowledgeJobAccess:  # noqa: C901
        # 调用者身份必须已由相应 audience 的 Principal 认证；这里不把 actor 字段当凭证。
        job = self.database.execute_one(
            "select j.id,j.internal_user_id,j.session_id,j.agent_publication_id,j.agent_config_hash,"
            "j.business_application_id,j.business_application_publication_id,"
            "j.business_application_config_hash,j.business_application_route_decision_json,"
            "s.application_publication_id as session_publication_id "
            "from agent_job j join app_user u on u.id=j.internal_user_id "
            "join agent_session s on s.id=j.session_id "
            "where j.id=? and j.internal_user_id=? and j.status='RUNNING' "
            "and u.status='enabled' and u.account_type='human'",
            (job_id, actor_id),
        )
        if (
            not job
            or not job["business_application_id"]
            or not job["business_application_publication_id"]
            or job["session_publication_id"] != job["business_application_publication_id"]
        ):
            raise self._invalid()
        verified = self.snapshots.verify(job_id)
        snapshot = verified["snapshot"]
        if (
            snapshot.get("job_id") != job_id
            or snapshot.get("application_publication_id")
            != job["business_application_publication_id"]
            or snapshot.get("agent_publication_id") != job["agent_publication_id"]
        ):
            raise self._invalid()
        expected = {**dict.fromkeys(KNOWLEDGE_TOOLS, KNOWLEDGE_SERVER), DETAIL_TOOL: "ones-mcp"}
        tools = {tool["tool_identifier"]: tool for tool in snapshot["tools"]}
        if any(
            tools.get(name, {}).get("server_code") != server for name, server in expected.items()
        ):
            raise self._invalid()
        publication = self.database.execute_one(
            "select application_id,schema_version,snapshot_json,config_hash "
            "from business_application_publication where id=?",
            (job["business_application_publication_id"],),
        )
        agent = self.database.execute_one(
            "select snapshot_json,config_hash,schema_version from agent_publication where id=?",
            (job["agent_publication_id"],),
        )
        if (
            not publication
            or not agent
            or agent["schema_version"] != 3
            or agent["config_hash"] != job["agent_config_hash"]
            or publication["application_id"] != job["business_application_id"]
            or publication["config_hash"] != job["business_application_config_hash"]
        ):
            raise self._invalid()
        try:
            published = json.loads(publication["snapshot_json"], object_pairs_hook=strict_object)
            agent_snapshot = json.loads(agent["snapshot_json"], object_pairs_hook=strict_object)
            route = json.loads(
                job["business_application_route_decision_json"], object_pairs_hook=strict_object
            )
            frozen = route["runtime_authorization"]
            valid = (
                isinstance(published, dict)
                and isinstance(agent_snapshot, dict)
                and agent_config_hash(agent_snapshot) == agent["config_hash"]
                and verify_publication_snapshot(
                    published,
                    schema_version=publication["schema_version"],
                    expected_hash=publication["config_hash"],
                )
                and published["agent"]["id"] == job["agent_publication_id"]
                and isinstance(frozen, dict)
                and fingerprint(frozen) == verified["authorization_hash"]
                and frozen["application_id"] == job["business_application_id"]
                and frozen["agent_publication_id"] == job["agent_publication_id"]
                and frozen["application_publication"]["id"]
                == job["business_application_publication_id"]
                and frozen["application_publication"]["config_hash"] == publication["config_hash"]
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            raise self._invalid() from None
        if not valid:
            raise self._invalid()
        envelope = agent_snapshot.get("mcp_tool_envelope")
        if not isinstance(envelope, list):
            raise self._invalid()
        AgentConfigRepository(self.database).verify_mcp_tool_facts(
            agent_publication_id=job["agent_publication_id"],
            envelopes=envelope,
        )
        AgentConfigRepository.verify_mcp_tool_policy(envelopes=envelope)
        published_tools = published.get("mcp_tools")
        if not isinstance(published_tools, list):
            raise self._invalid()
        for name, server in expected.items():
            matches = [
                item
                for item in published_tools
                if isinstance(item, dict) and item.get("tool_identifier") == name
            ]
            if (
                len(matches) != 1
                or matches[0].get("server_code") != server
                or any(
                    matches[0].get(key) != tools[name][key]
                    for key in (
                        "schema_hash",
                        "resource_kind",
                        "effect",
                        "confirmation_policy",
                        "operation_code",
                        "risk_level",
                        "target_policy",
                    )
                )
            ):
                raise self._invalid()
        for name, server in expected.items():
            row = self.database.execute_one(
                "select p.schema_hash,a.schema_hash as agent_schema_hash "
                "from business_application_publication_mcp_tool p "
                "join agent_publication_mcp_tool a on a.agent_publication_id=p.agent_publication_id "
                "and a.tool_identifier=p.tool_identifier and a.server_code=p.server_code "
                "where p.application_publication_id=? and p.agent_publication_id=? "
                "and p.tool_identifier=? and p.server_code=?",
                (
                    job["business_application_publication_id"],
                    job["agent_publication_id"],
                    name,
                    server,
                ),
            )
            if (
                not row
                or row["schema_hash"] != tools[name]["schema_hash"]
                or row["agent_schema_hash"] != tools[name]["schema_hash"]
            ):
                raise self._invalid()
        for tool in (*KNOWLEDGE_TOOLS, DETAIL_TOOL):
            self.authorization.require(
                user_id=actor_id,
                application_id=job["business_application_id"],
                tool_identifier=tool,
                stage="knowledge_read",
            )
        current = self.authorization.knowledge_access_projection(
            user_id=actor_id,
            application_id=job["business_application_id"],
            tool_identifiers=KNOWLEDGE_TOOLS,
        )
        # 老 Job 的冻结授权不能因后来的角色扩权而自动增加 KB。两次求值均逐记录联合匹配。
        frozen_ids: set[str] = set()
        grants = frozen.get("knowledge_grants")
        if not isinstance(grants, list):
            raise self._invalid()
        for grant in grants:
            if (
                not isinstance(grant, dict)
                or not isinstance(grant.get("knowledge_base_ids"), list)
                or not isinstance(grant.get("tool_identifiers"), list)
            ):
                raise self._invalid()
            if set(KNOWLEDGE_TOOLS).issubset(grant["tool_identifiers"]):
                frozen_ids.update(checked_identifier(key) for key in grant["knowledge_base_ids"])
        current_ids = {key for grant in current for key in grant["knowledge_base_ids"]}
        return KnowledgeJobAccess(
            job_id,
            actor_id,
            str(job["business_application_id"]),
            str(job["business_application_publication_id"]),
            verified["snapshot_hash"],
            verified["authorization_hash"],
            tuple(sorted(frozen_ids & current_ids)),
            fingerprint(
                self.authorization.knowledge_authorization_facts(
                    user_id=actor_id,
                    application_id=job["business_application_id"],
                )
            ),
        )

    def require(self, *, job_id: str, actor_id: str, knowledge_base_id: str) -> KnowledgeJobAccess:
        access = self.resolve(job_id=job_id, actor_id=actor_id)
        if knowledge_base_id not in access.knowledge_base_ids:
            raise self._invalid()
        return access

    def recheck(self, access: KnowledgeJobAccess) -> None:
        if self.resolve(job_id=access.job_id, actor_id=access.actor_id) != access:
            raise KnowledgeGovernanceError("knowledge_authorization_changed")
