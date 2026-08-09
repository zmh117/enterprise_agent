from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from services.data_mcp_server.runtime import DataResourceResolver, build_provider
from services.mcp_common.platform_store import PlatformRuntimeStore


class DataGenerationReconciler:
    """Build immutable Data MCP generations and switch deployment pointers atomically."""

    def __init__(
        self,
        store: PlatformRuntimeStore,
        resolver: DataResourceResolver,
        *,
        poll_seconds: float = 2.0,
        builder_id: str | None = None,
    ) -> None:
        self.store = store
        self.resolver = resolver
        self.poll_seconds = max(0.25, min(float(poll_seconds), 60.0))
        self.builder_id = (builder_id or f"data-mcp-{uuid.uuid4()}")[:128]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_forever,
            name="data-mcp-generation-reconciler",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(self.poll_seconds + 1.0, 5.0))
            self._thread = None

    def run_once(self, *, limit: int = 20) -> dict[str, int]:
        bounded = max(1, min(int(limit), 100))
        summary = {
            "secret_events": 0,
            "generations_activated": 0,
            "generations_failed": 0,
        }
        self._recover_stale_claims()
        for _ in range(bounded):
            event = self._claim_secret_event()
            if event is None:
                break
            summary["secret_events"] += 1
            self._process_secret_event(event)
        for _ in range(bounded):
            generation = self._claim_generation()
            if generation is None:
                break
            if self._build_generation(str(generation["id"])):
                summary["generations_activated"] += 1
            else:
                summary["generations_failed"] += 1
        return summary

    def status(self) -> dict[str, int | str]:
        rows = self.store.query.execute(
            """
            select latest.status, count(*) as count
              from mcp_resource_generation latest
              join mcp_resource_deployment d on d.id = latest.deployment_id
             where d.status = 'ACTIVE'
               and latest.resource_revision_id = d.resource_revision_id
               and latest.generation = (
                 select max(candidate.generation)
                   from mcp_resource_generation candidate
                  where candidate.deployment_id = latest.deployment_id
                    and candidate.resource_revision_id = d.resource_revision_id
               )
             group by latest.status
            """
        )
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        failed = counts.get("FAILED", 0)
        pending = counts.get("BUILDING", 0) + counts.get("VERIFYING", 0)
        return {
            "status": "degraded" if failed else ("building" if pending else "ready"),
            "active": counts.get("ACTIVE", 0),
            "building": pending,
            "failed": failed,
        }

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                # Safe degraded state is persisted per generation/event. Never log provider
                # exception strings because drivers may include connection material.
                pass
            self._stop.wait(self.poll_seconds)

    def _recover_stale_claims(self) -> None:
        stale = _iso(datetime.now(UTC) - timedelta(minutes=2))
        self.store.query.execute(
            """
            update mcp_resource_generation
               set status = 'BUILDING', claimed_at = null, builder_id = ''
             where status = 'VERIFYING' and claimed_at < ?
            """,
            (stale,),
        )
        self.store.query.execute(
            """
            update platform_secret_change_event
               set status = 'PENDING', claimed_at = null,
                   error_summary = 'stale consumer claim recovered'
             where status = 'RUNNING' and claimed_at < ? and attempt_count < 3
            """,
            (stale,),
        )
        self.store.query.execute(
            """
            update platform_secret_change_event
               set status = 'FAILED', processed_at = ?,
                   error_summary = 'secret generation trigger exhausted'
             where status = 'RUNNING' and claimed_at < ? and attempt_count >= 3
            """,
            (_iso(datetime.now(UTC)), stale),
        )

    def _claim_secret_event(self) -> dict[str, Any] | None:
        return self.store.query.execute_one(
            """
            with candidate as (
              select id from platform_secret_change_event
               where status = 'PENDING'
               order by created_at, id
               for update skip locked
               limit 1
            )
            update platform_secret_change_event e
               set status = 'RUNNING', attempt_count = attempt_count + 1,
                   claimed_at = ?
              from candidate
             where e.id = candidate.id
            returning e.*
            """,
            (_iso(datetime.now(UTC)),),
        )

    def _process_secret_event(self, event: dict[str, Any]) -> None:
        deployments = self.store.query.execute(
            """
            select distinct d.id, d.resource_revision_id, d.current_generation_id
              from mcp_resource_deployment d
              join mcp_resource_generation g on g.id = d.current_generation_id
              join mcp_resource_generation_secret_version gv
                on gv.generation_id = g.id
             where d.status = 'ACTIVE' and g.status = 'ACTIVE'
               and g.resource_revision_id = d.resource_revision_id
               and gv.secret_id = ?
            """,
            (event["secret_id"],),
        )
        succeeded = True
        for deployment in deployments:
            succeeded = self._enqueue_rotated_generation(deployment) and succeeded
        self.store.query.execute(
            """
            update platform_secret_change_event
               set status = ?, processed_at = ?,
                   error_summary = ?
             where id = ? and status = 'RUNNING'
            """,
            (
                "SUCCEEDED" if succeeded else "FAILED",
                _iso(datetime.now(UTC)),
                "" if succeeded else "related MCP generation could not be queued",
                event["id"],
            ),
        )

    def _enqueue_rotated_generation(self, deployment: dict[str, Any]) -> bool:
        versions = self.store.query.execute(
            """
            select s.id, s.active_version
              from mcp_resource_generation_secret_version current
              join platform_secret s on s.id = current.secret_id
              join platform_secret_version v
                on v.secret_id = s.id and v.version = s.active_version
             where current.generation_id = ?
               and s.status = 'enabled' and v.status = 'active'
             order by s.id
            """,
            (deployment["current_generation_id"],),
        )
        expected = self.store.query.execute_one(
            """
            select count(*) as count
              from mcp_resource_generation_secret_version
             where generation_id = ?
            """,
            (deployment["current_generation_id"],),
        )
        if len(versions) != int((expected or {}).get("count") or 0):
            return False
        digest = _hash_versions(versions)
        generation_id = f"mcp_resource_generation_{uuid.uuid4().hex}"
        timestamp = _iso(datetime.now(UTC))
        inserted = self.store.query.execute_one(
            """
            insert into mcp_resource_generation
              (id, deployment_id, resource_revision_id, generation,
               secret_versions_hash, status, safe_error_code, created_at,
               claimed_at, builder_id)
            select ?, d.id, d.resource_revision_id,
                   coalesce(max(g.generation), 0) + 1,
                   ?, 'BUILDING', '', ?, null, ''
              from mcp_resource_deployment d
              left join mcp_resource_generation g on g.deployment_id = d.id
             where d.id = ? and d.status = 'ACTIVE'
               and d.resource_revision_id = ?
               and not exists (
                 select 1 from mcp_resource_generation pending
                  where pending.deployment_id = d.id
                    and pending.status in ('BUILDING', 'VERIFYING')
               )
             group by d.id, d.resource_revision_id
            on conflict do nothing
            returning id
            """,
            (
                generation_id,
                digest,
                timestamp,
                deployment["id"],
                deployment["resource_revision_id"],
            ),
        )
        if inserted is None:
            return True
        for version in versions:
            self.store.query.execute(
                """
                insert into mcp_resource_generation_secret_version
                  (generation_id, secret_id, secret_version)
                values (?, ?, ?)
                """,
                (generation_id, version["id"], int(version["active_version"])),
            )
        return True

    def _claim_generation(self) -> dict[str, Any] | None:
        return self.store.query.execute_one(
            """
            with candidate as (
              select g.id
                from mcp_resource_generation g
                join mcp_resource_deployment d on d.id = g.deployment_id
               where g.status = 'BUILDING' and d.status = 'ACTIVE'
                 and g.resource_revision_id = d.resource_revision_id
               order by g.created_at, g.id
               for update of g skip locked
               limit 1
            )
            update mcp_resource_generation g
               set status = 'VERIFYING', claimed_at = ?, builder_id = ?
              from candidate
             where g.id = candidate.id
            returning g.*
            """,
            (_iso(datetime.now(UTC)), self.builder_id),
        )

    def _build_generation(self, generation_id: str) -> bool:
        try:
            resource = self.resolver.load_building_generation(generation_id)
            provider = build_provider(resource)
            asyncio.run(provider.health_check())
        except Exception:
            self.store.query.execute(
                """
                update mcp_resource_generation
                   set status = 'FAILED', safe_error_code = 'provider_verification_failed'
                 where id = ? and status = 'VERIFYING' and builder_id = ?
                """,
                (generation_id, self.builder_id),
            )
            return False
        try:
            with self.store.query.unit_of_work():
                target = self.store.query.execute_one(
                    """
              select g.id, g.deployment_id, g.resource_revision_id
                from mcp_resource_generation g
                join mcp_resource_deployment d on d.id = g.deployment_id
               where g.id = ? and g.status = 'VERIFYING' and g.builder_id = ?
                 and d.status = 'ACTIVE'
                 and d.resource_revision_id = g.resource_revision_id
               for update of g, d
                    """,
                    (generation_id, self.builder_id),
                )
                if target is None:
                    activated = None
                else:
                    self.store.query.execute(
                        """
                update mcp_resource_generation
                   set status = 'SUPERSEDED'
                 where deployment_id = ? and status = 'ACTIVE' and id <> ?
                        """,
                        (target["deployment_id"], generation_id),
                    )
                    activated = self.store.query.execute_one(
                        """
                update mcp_resource_generation
                   set status = 'ACTIVE', activated_at = ?,
                       safe_error_code = '', claimed_at = null
                 where id = ? and status = 'VERIFYING' and builder_id = ?
                returning id, deployment_id, resource_revision_id
                        """,
                        (
                            _iso(datetime.now(UTC)),
                            generation_id,
                            self.builder_id,
                        ),
                    )
                    if activated is None:
                        raise RuntimeError("MCP generation activation lost its claim")
                    switched = self.store.query.execute_one(
                        """
              update mcp_resource_deployment d
                 set current_generation_id = ?,
                     last_known_good_generation_id = ?,
                     updated_at = ?
               where d.id = ? and d.status = 'ACTIVE'
                 and d.resource_revision_id = ?
              returning d.id
                        """,
                        (
                            generation_id,
                            generation_id,
                            _iso(datetime.now(UTC)),
                            target["deployment_id"],
                            target["resource_revision_id"],
                        ),
                    )
                    if switched is None:
                        raise RuntimeError("MCP generation deployment switch failed")
        except Exception:
            self.store.query.execute(
                """
                update mcp_resource_generation
                   set status = 'FAILED', safe_error_code = 'generation_activation_failed'
                 where id = ? and status = 'VERIFYING' and builder_id = ?
                """,
                (generation_id, self.builder_id),
            )
            return False
        if activated is not None:
            return True
        self.store.query.execute(
            """
            update mcp_resource_generation
               set status = 'FAILED', safe_error_code = 'deployment_changed_during_build'
             where id = ? and status = 'VERIFYING' and builder_id = ?
            """,
            (generation_id, self.builder_id),
        )
        return False


def _hash_versions(rows: list[dict[str, Any]]) -> str:
    payload = {str(row["id"]): int(row["active_version"]) for row in rows}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
