from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from app.shared.database import Database

from .repository import json_text, new_id, now_iso


_RUNTIME_GENERATION_LOCK_KEY = 764589320242


@dataclass(frozen=True)
class GenerationTicket:
    id: str
    generation_no: int
    published_digest: str
    existing: bool = False


class RuntimeGenerationRepository:
    """Persistence for published facts and sanitized generation state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def published_resources(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select rr.id as resource_revision_id, rr.resource_id,
                   rr.revision, rr.provider_type,
                   rr.provider_contract_version, rr.config_json,
                   rr.secret_refs_json, rr.content_hash,
                   r.code as resource_code, r.resource_kind, r.scope_type,
                   r.environment_id, coalesce(r.base_id, '') as base_id,
                   coalesce(r.workshop_id, '') as workshop_id,
                   e.code as environment_code,
                   coalesce(b.code, '') as base_code,
                   coalesce(w.code, '') as workshop_code
              from platform_resource_revision rr
              join platform_resource r on r.id = rr.resource_id
              join platform_environment e on e.id = r.environment_id
              left join platform_base b on b.id = r.base_id
              left join platform_workshop w on w.id = r.workshop_id
             where rr.status = 'PUBLISHED'
               and r.status = 'enabled'
             order by r.code, rr.revision, rr.id
            """
        )
        return [
            {
                **row,
                "revision": int(row["revision"]),
                "config": self._json_object(row["config_json"]),
                "secret_refs": self._json_object(row["secret_refs_json"]),
            }
            for row in rows
        ]

    def active_application_bindings(self) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select distinct
                   p.id as application_publication_id,
                   p.application_id,
                   a.code as application_code,
                   r.resource_revision_id
              from business_application_deployment d
              join business_application_publication p
                on p.id = d.publication_id
              join business_application a on a.id = p.application_id
              join business_application_publication_builtin_tool tool
                on tool.application_publication_id = p.id
              join business_application_publication_builtin_tool_resource r
                on r.application_tool_id = tool.id
             where d.active = 1
               and a.status = 'enabled'
             order by p.id, r.resource_revision_id
            """
        )
        return rows

    def active_secret_versions(
        self,
        refs: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        normalized = sorted({str(value) for value in refs if value})
        if not normalized:
            return {}
        placeholders = ", ".join("?" for _ in normalized)
        rows = self.database.execute(
            f"""
            select s.ref, s.id as secret_id, s.active_version,
                   v.id as secret_version_id, v.version
              from platform_secret s
              join platform_secret_version v
                on v.secret_id = s.id
               and v.version = s.active_version
               and v.status = 'active'
             where s.status = 'enabled'
               and s.ref in ({placeholders})
             order by s.ref
            """,
            normalized,
        )
        return {
            str(row["ref"]): {
                "secret_id": str(row["secret_id"]),
                "secret_version_id": str(row["secret_version_id"]),
                "version": int(row["version"]),
            }
            for row in rows
        }

    def published_digest(self) -> str:
        resources = self.published_resources()
        applications = self.active_application_bindings()
        refs = [
            str(ref)
            for resource in resources
            for ref in resource["secret_refs"].values()
        ]
        payload = {
            "resources": [
                {
                    key: value
                    for key, value in resource.items()
                    if key not in {"config_json", "secret_refs_json"}
                }
                for resource in resources
            ],
            "application_bindings": applications,
            "secret_versions": self.active_secret_versions(refs),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def begin_generation(self, published_digest: str) -> GenerationTicket:
        with self.database.unit_of_work():
            if self.database.engine == "postgres":
                self.database.execute(
                    "select pg_advisory_xact_lock(?)",
                    (_RUNTIME_GENERATION_LOCK_KEY,),
                )
            active = self.active_generation()
            if (
                active is not None
                and str(active["published_digest"]) == published_digest
            ):
                return GenerationTicket(
                    id=str(active["id"]),
                    generation_no=int(active["generation_no"]),
                    published_digest=published_digest,
                    existing=True,
                )
            row = self.database.execute_one(
                """
                select coalesce(max(generation_no), 0) as generation_no
                  from runtime_snapshot_generation
                """
            )
            generation_no = int(row["generation_no"] if row else 0) + 1
            generation_id = new_id("runtime_generation")
            self.database.execute(
                """
                insert into runtime_snapshot_generation
                  (id, generation_no, published_digest, snapshot_digest,
                   status, resource_count, application_count, snapshot_json,
                   error_code, error_summary, built_at)
                values (?, ?, ?, '', 'BUILDING', 0, 0, '{}', '', '', ?)
                """,
                (
                    generation_id,
                    generation_no,
                    published_digest,
                    now_iso(),
                ),
            )
            return GenerationTicket(
                id=generation_id,
                generation_no=generation_no,
                published_digest=published_digest,
            )

    def activate_generation(
        self,
        ticket: GenerationTicket,
        *,
        snapshot_digest: str,
        snapshot_metadata: dict[str, Any],
        resource_states: Iterable[dict[str, Any]],
        application_states: Iterable[dict[str, Any]],
    ) -> GenerationTicket:
        resources = list(resource_states)
        applications = list(application_states)
        timestamp = now_iso()
        with self.database.unit_of_work():
            if self.database.engine == "postgres":
                self.database.execute(
                    "select pg_advisory_xact_lock(?)",
                    (_RUNTIME_GENERATION_LOCK_KEY,),
                )
            active = self.active_generation()
            if active is not None and str(active["id"]) != ticket.id:
                if str(active["published_digest"]) == ticket.published_digest:
                    self.database.execute(
                        """
                        update runtime_snapshot_generation
                           set status = 'SUPERSEDED',
                               error_code = 'duplicate_generation',
                               error_summary = '相同发布事实已由另一实例激活'
                         where id = ? and status = 'BUILDING'
                        """,
                        (ticket.id,),
                    )
                    return GenerationTicket(
                        id=str(active["id"]),
                        generation_no=int(active["generation_no"]),
                        published_digest=ticket.published_digest,
                        existing=True,
                    )
                if int(active["generation_no"]) > ticket.generation_no:
                    self.database.execute(
                        """
                        update runtime_snapshot_generation
                           set status = 'FAILED',
                               error_code = 'published_generation_stale',
                               error_summary = '构建期间发布事实已变化'
                         where id = ? and status = 'BUILDING'
                        """,
                        (ticket.id,),
                    )
                    raise RuntimeError(
                        "Published runtime facts changed during generation build"
                    )
                self.database.execute(
                    """
                    update runtime_snapshot_generation
                       set status = 'SUPERSEDED'
                     where id = ? and status = 'ACTIVE'
                    """,
                    (str(active["id"]),),
                )
            for state in resources:
                self.database.execute(
                    """
                    insert into tool_resource_runtime_state
                      (resource_revision_id, generation_id,
                       effective_revision_id, status,
                       resolved_secret_versions_json,
                       last_known_good_generation_id, error_code,
                       error_summary, checked_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state["resource_revision_id"],
                        ticket.id,
                        state.get("effective_revision_id") or None,
                        state["status"],
                        json_text(
                            state.get("resolved_secret_versions") or {}
                        ),
                        state.get("last_known_good_generation_id") or None,
                        state.get("error_code") or "",
                        state.get("error_summary") or "",
                        timestamp,
                    ),
                )
            for state in applications:
                self.database.execute(
                    """
                    insert into business_application_runtime_state
                      (application_publication_id, generation_id,
                       effective_application_publication_id, status,
                       last_known_good_generation_id, reason_codes_json,
                       updated_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state["application_publication_id"],
                        ticket.id,
                        state.get(
                            "effective_application_publication_id"
                        )
                        or None,
                        state["status"],
                        state.get("last_known_good_generation_id") or None,
                        json_text(state.get("reason_codes") or []),
                        timestamp,
                    ),
                )
            self.database.execute(
                """
                update runtime_snapshot_generation
                   set snapshot_digest = ?, status = 'ACTIVE',
                       resource_count = ?, application_count = ?,
                       snapshot_json = ?, activated_at = ?,
                       error_code = '', error_summary = ''
                 where id = ? and status = 'BUILDING'
                """,
                (
                    snapshot_digest,
                    len(resources),
                    len(applications),
                    json_text(snapshot_metadata),
                    timestamp,
                    ticket.id,
                ),
            )
        return ticket

    def fail_generation(
        self,
        ticket: GenerationTicket,
        *,
        error_code: str,
        error_summary: str,
    ) -> None:
        if ticket.existing:
            return
        self.database.execute(
            """
            update runtime_snapshot_generation
               set status = 'FAILED', error_code = ?, error_summary = ?
             where id = ? and status = 'BUILDING'
            """,
            (error_code, error_summary, ticket.id),
        )

    def active_generation(self) -> dict[str, Any] | None:
        return self.database.execute_one(
            """
            select *
              from runtime_snapshot_generation
             where status = 'ACTIVE'
             order by generation_no desc
             limit 1
            """
        )

    def latest_states(self) -> dict[str, Any]:
        generation = self.active_generation()
        if generation is None:
            return {
                "generation": None,
                "resources": [],
                "applications": [],
            }
        resources = self.database.execute(
            """
            select * from tool_resource_runtime_state
             where generation_id = ?
             order by resource_revision_id
            """,
            (generation["id"],),
        )
        applications = self.database.execute(
            """
            select * from business_application_runtime_state
             where generation_id = ?
             order by application_publication_id
            """,
            (generation["id"],),
        )
        return {
            "generation": generation,
            "resources": resources,
            "applications": applications,
        }

    def public_status(self) -> dict[str, Any]:
        latest = self.latest_states()
        generation = latest["generation"]
        if generation is None:
            return {
                "observed_published_generation": None,
                "effective_generation": None,
                "status": "EMPTY",
                "resources": [],
                "applications": [],
            }
        resources = [
            {
                "resource_revision_id": str(
                    row["resource_revision_id"]
                ),
                "effective_revision_id": str(
                    row.get("effective_revision_id") or ""
                ),
                "status": str(row["status"]),
                "resolved_secret_versions": self._json_object(
                    row.get("resolved_secret_versions_json") or "{}"
                ),
                "last_known_good_generation_id": str(
                    row.get("last_known_good_generation_id") or ""
                ),
                "error_code": str(row.get("error_code") or ""),
                "error_summary": str(
                    row.get("error_summary") or ""
                ),
            }
            for row in latest["resources"]
        ]
        applications = [
            {
                "application_publication_id": str(
                    row["application_publication_id"]
                ),
                "effective_application_publication_id": str(
                    row.get(
                        "effective_application_publication_id"
                    )
                    or ""
                ),
                "status": str(row["status"]),
                "last_known_good_generation_id": str(
                    row.get("last_known_good_generation_id") or ""
                ),
                "reason_codes": self._json_list(
                    row.get("reason_codes_json") or "[]"
                ),
            }
            for row in latest["applications"]
        ]
        aggregate = "READY"
        if any(row["status"] == "BLOCKED" for row in applications):
            aggregate = "BLOCKED"
        elif any(
            row["status"] == "DEGRADED" for row in applications
        ):
            aggregate = "DEGRADED"
        return {
            "observed_published_generation": {
                "id": str(generation["id"]),
                "number": int(generation["generation_no"]),
                "digest": str(generation["published_digest"]),
            },
            "effective_generation": {
                "id": str(generation["id"]),
                "number": int(generation["generation_no"]),
                "digest": str(generation["snapshot_digest"]),
            },
            "status": aggregate,
            "resources": resources,
            "applications": applications,
        }

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        try:
            decoded = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        try:
            decoded = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
