from __future__ import annotations

import json
from typing import Any

from app.modules.api_capability.domain.contracts import content_hash
from app.modules.api_capability.domain.publication import (
    read_agent_capability_envelope,
    read_application_capability_allowlist,
)
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class CapabilityPublicationRepository:
    """Freeze exact API Capability releases into immutable publications."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def freeze_agent_envelope(
        self,
        agent_publication_id: str,
        *,
        release_ids: list[str],
    ) -> tuple[Any, ...]:
        publication = self._publication(
            "agent_publication",
            agent_publication_id,
            "Agent Publication",
        )
        existing_rows = self.database.execute(
            """
            select * from agent_publication_api_capability
             where agent_publication_id = ? order by binding_order
            """,
            (agent_publication_id,),
        )
        requested = _unique_ids(release_ids)
        if existing_rows:
            raise self._already_frozen("Agent")
        entries = tuple(self.prepare_agent_envelope(requested))
        snapshot = _json_object(publication.get("snapshot_json"))
        frozen_ids = [
            str(item.get("release_id") or "")
            for item in snapshot.get("capability_envelope") or []
            if isinstance(item, dict)
        ]
        if "capability_envelope" in snapshot and frozen_ids != requested:
            raise self._already_frozen("Agent")
        snapshot["capability_envelope"] = list(entries)
        with self.database.unit_of_work():
            for index, entry in enumerate(entries):
                self.database.execute(
                    """
                    insert into agent_publication_api_capability
                      (id, agent_publication_id, binding_order, identifier,
                       capability_release_id, capability_revision_id,
                       handler_revision_id, schema_hash, description, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("agent_publication_api_capability"),
                        agent_publication_id,
                        index,
                        entry["identifier"],
                        entry["release_id"],
                        entry["capability_revision_id"],
                        entry["handler_revision_id"],
                        entry["schema_hash"],
                        entry["description"],
                        now_iso(),
                    ),
                )
            self.database.execute(
                """
                update agent_publication
                   set snapshot_json = ?, config_hash = ?
                 where id = ?
                """,
                (
                    _json_text(snapshot),
                    content_hash(snapshot),
                    agent_publication_id,
                ),
            )
        return read_agent_capability_envelope(snapshot)

    def freeze_application_allowlist(
        self,
        application_publication_id: str,
        *,
        agent_publication_id: str,
        release_ids: list[str],
    ) -> tuple[Any, ...]:
        publication = self._publication(
            "business_application_publication",
            application_publication_id,
            "Application Publication",
        )
        existing_rows = self.database.execute(
            """
            select * from business_application_publication_api_capability
             where application_publication_id = ? order by binding_order
            """,
            (application_publication_id,),
        )
        requested = _unique_ids(release_ids)
        if existing_rows:
            raise self._already_frozen("Application")
        entries = tuple(
            self.prepare_application_allowlist(
                agent_publication_id,
                requested,
                require_active=True,
            )
        )
        snapshot = _json_object(publication.get("snapshot_json"))
        frozen_ids = [
            str(item.get("release_id") or "")
            for item in snapshot.get("capability_allowlist") or []
            if isinstance(item, dict)
        ]
        frozen_agent = str(snapshot.get("capability_agent_publication_id") or "")
        if "capability_allowlist" in snapshot and (
            frozen_ids != requested or frozen_agent != agent_publication_id
        ):
            raise self._already_frozen("Application")
        snapshot["capability_allowlist"] = list(entries)
        snapshot["capability_agent_publication_id"] = agent_publication_id
        with self.database.unit_of_work():
            for index, entry in enumerate(entries):
                self.database.execute(
                    """
                    insert into business_application_publication_api_capability
                      (id, application_publication_id, agent_publication_id,
                       binding_order, identifier, capability_release_id,
                       created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("application_publication_api_capability"),
                        application_publication_id,
                        agent_publication_id,
                        index,
                        entry["identifier"],
                        entry["release_id"],
                        now_iso(),
                    ),
                )
            self.database.execute(
                """
                update business_application_publication
                   set snapshot_json = ?, config_hash = ?
                 where id = ?
                """,
                (
                    _json_text(snapshot),
                    content_hash(snapshot),
                    application_publication_id,
                ),
            )
        return read_application_capability_allowlist(snapshot)

    def prepare_agent_envelope(
        self,
        release_ids: list[str],
    ) -> list[dict[str, Any]]:
        releases = self._active_releases(release_ids)
        identifiers = [str(item["identifier"]) for item in releases]
        if len(identifiers) != len(set(identifiers)):
            raise NonRetryableExecutionError(
                "Agent Capability Envelope has duplicate identifiers",
                safe_message="同一 Agent 不能选择同名 Capability 的多个版本",
                error_code="capability_identifier_duplicate",
            )
        return [
            {
                "identifier": str(release["identifier"]),
                "release_id": str(release["id"]),
                "capability_revision_id": str(release["capability_revision_id"]),
                "handler_revision_id": str(release["handler_revision_id"]),
                "schema_hash": str(release["schema_hash"]),
                "description": str(release["description"]),
                "release_revision": int(release["release_revision"]),
            }
            for release in releases
        ]

    def prepare_application_allowlist(
        self,
        agent_publication_id: str,
        release_ids: list[str],
        *,
        require_active: bool,
    ) -> list[dict[str, Any]]:
        self._publication(
            "agent_publication",
            agent_publication_id,
            "Agent Publication",
        )
        envelope_rows = self.database.execute(
            """
            select e.*, r.status
              from agent_publication_api_capability e
              join api_capability_release r
                on r.id = e.capability_release_id
             where e.agent_publication_id = ?
             order by e.binding_order
            """,
            (agent_publication_id,),
        )
        envelope_by_release = {str(row["capability_release_id"]): row for row in envelope_rows}
        requested = _unique_ids(release_ids)
        missing = [release_id for release_id in requested if release_id not in envelope_by_release]
        if missing:
            raise NonRetryableExecutionError(
                "Application allowlist exceeds Agent Capability Envelope",
                safe_message="应用只能选择当前 Agent 发布版本已拥有的 Capability",
                error_code="capability_not_in_agent_envelope",
            )
        if require_active:
            unavailable = [
                release_id
                for release_id in requested
                if str(envelope_by_release[release_id]["status"]) != "ACTIVE"
            ]
            if unavailable:
                raise NonRetryableExecutionError(
                    "Application selected a non-ACTIVE Capability Release",
                    safe_message=("所选 Capability 已废弃或停用，请显式替换或移除"),
                    error_code="capability_release_not_selectable",
                )
        return [
            {
                "identifier": str(envelope_by_release[release_id]["identifier"]),
                "release_id": release_id,
            }
            for release_id in requested
        ]

    def agent_envelope_catalog(
        self,
        agent_publication_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            select e.identifier, e.capability_release_id as release_id,
                   e.description, r.release_revision, r.status,
                   r.release_note, r.deprecation_reason,
                   r.replacement_release_id
              from agent_publication_api_capability e
              join api_capability_release r
                on r.id = e.capability_release_id
             where e.agent_publication_id = ?
             order by e.binding_order
            """,
            (agent_publication_id,),
        )
        return [
            {
                **row,
                "release_revision": int(row["release_revision"]),
                "selectable": str(row["status"]) == "ACTIVE",
            }
            for row in rows
        ]

    def get_agent_envelope(
        self,
        agent_publication_id: str,
    ) -> tuple[Any, ...]:
        publication = self._publication(
            "agent_publication",
            agent_publication_id,
            "Agent Publication",
        )
        return read_agent_capability_envelope(_json_object(publication.get("snapshot_json")))

    def get_application_allowlist(
        self,
        application_publication_id: str,
    ) -> tuple[Any, ...]:
        publication = self._publication(
            "business_application_publication",
            application_publication_id,
            "Application Publication",
        )
        return read_application_capability_allowlist(_json_object(publication.get("snapshot_json")))

    def _active_releases(
        self,
        release_ids: list[str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for release_id in _unique_ids(release_ids):
            row = self.database.execute_one(
                """
                select r.*, c.description,
                       c.input_schema_json, c.output_schema_json
                  from api_capability_release r
                  join api_capability_revision c
                    on c.id = r.capability_revision_id
                 where r.id = ?
                """,
                (release_id,),
            )
            if row is None:
                raise NotFound(
                    "Capability Release not found",
                    safe_message="未找到 Capability Release",
                )
            if str(row["status"]) != "ACTIVE":
                raise NonRetryableExecutionError(
                    "Only ACTIVE Capability Releases can be selected",
                    safe_message="只能选择 ACTIVE Capability Release",
                    error_code="capability_release_not_selectable",
                )
            row["schema_hash"] = content_hash(
                {
                    "schema_version": 1,
                    "input_schema": _json_object(row["input_schema_json"]),
                    "output_schema": _json_object(row["output_schema_json"]),
                }
            )
            rows.append(row)
        return rows

    def _publication(
        self,
        table: str,
        publication_id: str,
        label: str,
    ) -> dict[str, Any]:
        if table not in {
            "agent_publication",
            "business_application_publication",
        }:
            raise ValueError("Unsupported publication table")
        row = self.database.execute_one(
            f"select * from {table} where id = ?",
            (publication_id,),
        )
        if row is None:
            raise NotFound(
                f"{label} not found",
                safe_message=f"未找到 {label}",
            )
        return row

    @staticmethod
    def _already_frozen(label: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            f"{label} Capability snapshot is already frozen",
            safe_message=f"{label} Capability 快照已冻结，不能原地修改",
            error_code="publication_snapshot_immutable",
        )


def _unique_ids(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
