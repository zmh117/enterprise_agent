"""当前授权知识库目录；游标不持久化业务数据，不给予后续调用任何授权。"""

from dataclasses import asdict
import json
import time
from collections.abc import Callable
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.modules.audit.application.audit_service import AuditService
from app.modules.knowledge.domain.governance import (
    KnowledgeGovernanceError,
    checked_identifier,
    strict_object,
)
from app.modules.knowledge.domain.models import KnowledgeJobAccess
from app.modules.knowledge.application.ports import PrincipalAccess
from app.modules.knowledge.domain.models import OnesKnowledgeIdentity
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.domain.vector_contract import fingerprint


PAGE_SIZE = 50
MAX_CURSOR_CHARS = 4096
CURSOR_TTL_SECONDS = 300
_UNAVAILABLE = frozenset(
    {
        "knowledge_resource_unavailable",
        "knowledge_source_unavailable",
        "knowledge_source_changed",
        "knowledge_index_unavailable",
    }
)


class KnowledgeDirectory:
    def __init__(
        self,
        access: PrincipalAccess,
        resources: KnowledgeResourceReader,
        audit: AuditService,
        *,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.access = access
        self.resources = resources
        self.audit = audit
        self._clock = clock or (lambda: int(time.time()))
        # 独立进程内临时密钥；重启后旧游标失效，从首页恢复，不新增共享 Secret 或游标表。
        self._cursors = Fernet(Fernet.generate_key())

    @staticmethod
    def _binding(access: KnowledgeJobAccess) -> str:
        return fingerprint(
            {
                name: getattr(access, name)
                for name in (
                    "job_id",
                    "actor_id",
                    "application_id",
                    "application_publication_id",
                    "snapshot_hash",
                    "authorization_hash",
                )
            }
        )

    def _catalog(
        self, access: KnowledgeJobAccess, identity: OnesKnowledgeIdentity
    ) -> tuple[list[dict[str, Any]], str]:
        items, facts = [], []
        for base_id in access.knowledge_base_ids:
            try:
                pin = self.resources.resolve(base_id)
            except KnowledgeGovernanceError as exc:
                if exc.error_code not in _UNAVAILABLE:
                    raise
                continue
            binding = self.resources.store.get("source_binding", pin.binding_id)
            if (
                binding["instance_code"] != identity.instance_code
                or binding["team_id"] != identity.team_id
            ):
                continue
            base = self.resources.store.get("knowledge_base", base_id)
            resource = self.resources.store.get("retrieval_resource", pin.resource_id)
            item = {
                "knowledge_base_id": base_id,
                "code": base["code"],
                "name": resource["name"],
                "status": "AVAILABLE",
            }
            items.append(item)
            facts.append({"resource": asdict(pin), "view": item})
        items.sort(key=lambda item: item["knowledge_base_id"])
        facts.sort(key=lambda item: item["resource"]["knowledge_base_id"])
        return items, fingerprint(
            {
                "resources": facts,
                "identity": asdict(identity),
                "authorization": access.current_authorization_hash,
            }
        )

    def _position(self, cursor: str, binding: str, state: str) -> str:
        try:
            raw = self._cursors.decrypt_at_time(
                cursor.encode("ascii"),
                ttl=CURSOR_TTL_SECONDS,
                current_time=self._clock(),
            )
            value = json.loads(raw, object_pairs_hook=strict_object)
            if (
                not isinstance(value, dict)
                or set(value) != {"v", "binding", "state", "after"}
                or value["v"] != 1
                or value["binding"] != binding
            ):
                raise ValueError
            after = checked_identifier(value["after"])
            if value["state"] != state:
                raise KnowledgeGovernanceError("knowledge_cursor_stale")
            return after
        except (InvalidToken, ValueError, UnicodeError, TypeError, KeyError, RecursionError):
            raise KnowledgeGovernanceError("knowledge_cursor_invalid") from None

    def list_bases(self, *, token: str, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict) or not set(arguments) <= {"cursor"}:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        cursor = arguments.get("cursor")
        if "cursor" in arguments and (
            not isinstance(cursor, str) or not 1 <= len(cursor) <= MAX_CURSOR_CHARS
        ):
            raise KnowledgeGovernanceError("knowledge_cursor_invalid")
        access = self.access.authenticate(token, "knowledge_list_bases")
        identity = self.access.identity(access.actor_id)
        items, state = self._catalog(access, identity)
        binding = self._binding(access)
        after = self._position(cursor, binding, state) if cursor else ""
        if after and not any(item["knowledge_base_id"] == after for item in items):
            raise KnowledgeGovernanceError("knowledge_cursor_invalid")
        remaining = [item for item in items if item["knowledge_base_id"] > after]
        page, more = remaining[:PAGE_SIZE], len(remaining) > PAGE_SIZE
        next_cursor = None
        if more:
            next_cursor = self._cursors.encrypt_at_time(
                json.dumps(
                    {
                        "v": 1,
                        "binding": binding,
                        "state": state,
                        "after": page[-1]["knowledge_base_id"],
                    },
                    separators=(",", ":"),
                ).encode(),
                self._clock(),
            ).decode("ascii")
        # 包括页外新增/停用的资源，避免以第一页的允许状态代替后续页面授权。
        current = self.access.authenticate(token, "knowledge_list_bases")
        current_identity = self.access.identity(access.actor_id)
        if (
            current != access
            or current_identity != identity
            or self._catalog(current, current_identity)[1] != state
        ):
            raise KnowledgeGovernanceError("knowledge_cursor_stale")
        self.audit.record(
            "knowledge.directory.listed",
            status="success",
            summary="已返回当前授权知识库目录",
            actor_id=access.actor_id,
            job_id=access.job_id,
            payload={"returned": len(page), "has_more": more},
        )
        return {"items": page, "has_more": more, "next_cursor": next_cursor}
