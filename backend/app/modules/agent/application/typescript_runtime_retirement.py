from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.modules.agent.infrastructure.runtime_protocol import (
    CURRENT_RUNTIME_PROTOCOL_VERSION,
)
from app.modules.job.domain.job_status import JobStatus
from app.shared.database import Database


TYPESCRIPT_RUNTIME_KIND = "typescript-v1"
PYTHON_RUNTIME_KIND = "python-v1"
NON_TERMINAL_JOB_STATUSES = (
    JobStatus.WAITING_INPUT.value,
    JobStatus.PENDING.value,
    JobStatus.RUNNING.value,
    JobStatus.RETRY_WAIT.value,
)
NON_TERMINAL_OUTBOX_STATUSES = ("PENDING", "RUNNING", "RETRY_WAIT")
REQUIRED_QUEUE_LABELS = (
    "job_queue",
    "retry_queue",
    "dead_queue",
    "legacy_retry_queue",
)
EXECUTABLE_QUEUE_LABELS = (
    "job_queue",
    "retry_queue",
    "legacy_retry_queue",
)
TYPESCRIPT_RUNTIME_ENV_KEYS = (
    "TYPESCRIPT_AGENT_RUNTIME_URL",
    "TYPESCRIPT_AGENT_RUNTIME_ALLOWED_HOSTS",
)


class TypeScriptRuntimeRetirementPreflight:
    """Read-only, redacted evidence for retiring the TypeScript Agent Runtime."""

    def __init__(
        self,
        *,
        database: Database,
        queue_inspector: Callable[[], Mapping[str, object]],
        target_environment: str,
        observed_environment: str,
        expected_environments: Sequence[str],
        checkout: Mapping[str, object],
        environ: Mapping[str, str],
    ) -> None:
        self.database = database
        self.queue_inspector = queue_inspector
        self.target_environment = target_environment.strip()
        self.observed_environment = observed_environment.strip()
        self.expected_environments = tuple(
            sorted({item.strip() for item in expected_environments if item.strip()})
        )
        self.checkout = dict(checkout)
        self.environ = environ

    def run(self) -> dict[str, object]:
        blocker_codes: list[str] = []
        database_report = self._database_report(blocker_codes)
        queue_report = self._queue_report(blocker_codes)
        checkout_report = self._checkout_report(blocker_codes)
        coverage = self._coverage_report(
            database_ready=database_report.get("status") == "ready",
            queue_ready=queue_report.get("status") == "ready",
            blocker_codes=blocker_codes,
        )
        runtime_configuration = self._runtime_configuration_report(
            database_report,
            blocker_codes,
        )

        return {
            "status": "ready" if not blocker_codes else "blocked",
            "write_performed": False,
            "target_environment": self.target_environment,
            "observed_environment": self.observed_environment,
            "checkout": checkout_report,
            "coverage": coverage,
            "runtime": {
                "default_runtime": PYTHON_RUNTIME_KIND,
                "retiring_runtime": TYPESCRIPT_RUNTIME_KIND,
                "protocol_version": CURRENT_RUNTIME_PROTOCOL_VERSION,
            },
            "database": database_report,
            "queue": queue_report,
            "runtime_configuration": runtime_configuration,
            "blocker_codes": _deduplicate(blocker_codes),
        }

    def _database_report(self, blocker_codes: list[str]) -> dict[str, object]:
        try:
            schema = self.database.execute_one(
                "select version from schema_migration order by version desc limit 1"
            )
            definitions = self.database.execute(
                """
                select id, code, status, current_publication_id
                  from agent_definition
                 where runtime_kind = ?
                 order by id
                """,
                (TYPESCRIPT_RUNTIME_KIND,),
            )
            publications = self.database.execute(
                """
                select id, agent_id, revision, status
                  from agent_publication
                 where runtime_kind = ?
                 order by id
                """,
                (TYPESCRIPT_RUNTIME_KIND,),
            )
            application_publications = self.database.execute(
                """
                select publication.id as application_publication_id,
                       revision.application_id,
                       revision.agent_publication_id
                  from business_application_publication publication
                  join business_application_revision revision
                    on revision.id = publication.revision_id
                  join agent_publication agent_publication
                    on agent_publication.id = revision.agent_publication_id
                 where agent_publication.runtime_kind = ?
                 order by publication.id
                """,
                (TYPESCRIPT_RUNTIME_KIND,),
            )
            active_deployments = self.database.execute(
                """
                select deployment.id as deployment_id,
                       deployment.application_id,
                       deployment.environment,
                       deployment.publication_id
                  from business_application_deployment deployment
                  join business_application_publication publication
                    on publication.id = deployment.publication_id
                  join business_application_revision revision
                    on revision.id = publication.revision_id
                  join agent_publication agent_publication
                    on agent_publication.id = revision.agent_publication_id
                 where deployment.active = 1
                   and deployment.environment = ?
                   and agent_publication.runtime_kind = ?
                 order by deployment.id
                """,
                (self.target_environment, TYPESCRIPT_RUNTIME_KIND),
            )
            job_counts = self.database.execute(
                """
                select status, count(*) as count
                  from agent_job
                 where agent_runtime_kind = ?
                 group by status
                 order by status
                """,
                (TYPESCRIPT_RUNTIME_KIND,),
            )
            non_terminal_jobs = self.database.execute(
                """
                select id, status
                  from agent_job
                 where agent_runtime_kind = ?
                   and status in (?, ?, ?, ?)
                 order by id
                """,
                (TYPESCRIPT_RUNTIME_KIND, *NON_TERMINAL_JOB_STATUSES),
            )
            outbox_counts = self.database.execute(
                """
                select outbox.status, count(*) as count
                  from job_dispatch_outbox outbox
                  join agent_job job on job.id = outbox.job_id
                 where job.agent_runtime_kind = ?
                 group by outbox.status
                 order by outbox.status
                """,
                (TYPESCRIPT_RUNTIME_KIND,),
            )
            non_terminal_outbox = self.database.execute(
                """
                select outbox.id, outbox.job_id, outbox.status
                  from job_dispatch_outbox outbox
                  join agent_job job on job.id = outbox.job_id
                 where job.agent_runtime_kind = ?
                   and outbox.status in (?, ?, ?)
                 order by outbox.id
                """,
                (TYPESCRIPT_RUNTIME_KIND, *NON_TERMINAL_OUTBOX_STATUSES),
            )
            runtime_config = self.database.execute(
                """
                select distinct
                       coalesce(value.key, definition.key) as key,
                       coalesce(value.status, definition.status) as status,
                       coalesce(value.service_name, '') as service_name
                 from platform_runtime_config_definition definition
                  left join platform_runtime_config_value value
                    on value.definition_id = definition.id
                 where lower(definition.key) like ?
                    or lower(definition.service_names_json) like ?
                    or lower(coalesce(value.key, '')) like ?
                    or lower(coalesce(value.service_name, '')) = ?
                 order by key, service_name
                """,
                (
                    "%typescript%runtime%",
                    "%typescript-agent-runtime%",
                    "%typescript%runtime%",
                    "typescript-agent-runtime",
                ),
            )
        except Exception as exc:
            blocker_codes.append("database_unavailable")
            return {
                "status": "unavailable",
                "error_code": _safe_error_code("database", exc),
            }

        current_publication_ids = {
            str(item.get("current_publication_id") or "") for item in definitions
        }
        current_typescript_publications = [
            item for item in publications if str(item.get("id") or "") in current_publication_ids
        ]
        if active_deployments:
            blocker_codes.append("typescript_active_deployment")
        if non_terminal_jobs:
            blocker_codes.append("typescript_non_terminal_jobs")
        if non_terminal_outbox:
            blocker_codes.append("typescript_non_terminal_outbox")
        if runtime_config:
            blocker_codes.append("typescript_database_runtime_configuration")

        return {
            "status": "ready",
            "schema_head": str((schema or {}).get("version") or "none"),
            "typescript_definitions": _identifiers(
                definitions,
                fields=("id", "code", "status", "current_publication_id"),
            ),
            "typescript_publications": _identifiers(
                publications,
                fields=("id", "agent_id", "revision", "status"),
            ),
            "current_typescript_publication_ids": [
                str(item["id"]) for item in current_typescript_publications
            ],
            "typescript_application_publications": _identifiers(
                application_publications,
                fields=(
                    "application_publication_id",
                    "application_id",
                    "agent_publication_id",
                ),
            ),
            "active_typescript_deployments": _identifiers(
                active_deployments,
                fields=("deployment_id", "application_id", "environment", "publication_id"),
            ),
            "typescript_jobs_by_status": {
                str(item["status"]): int(item["count"]) for item in job_counts
            },
            "non_terminal_typescript_jobs": _identifiers(
                non_terminal_jobs,
                fields=("id", "status"),
            ),
            "typescript_dispatch_outbox_by_status": {
                str(item["status"]): int(item["count"]) for item in outbox_counts
            },
            "non_terminal_typescript_dispatch_outbox": _identifiers(
                non_terminal_outbox,
                fields=("id", "job_id", "status"),
            ),
            "typescript_runtime_config_keys": _identifiers(
                runtime_config,
                fields=("key", "status", "service_name"),
            ),
        }

    def _queue_report(self, blocker_codes: list[str]) -> dict[str, object]:
        try:
            topology = dict(self.queue_inspector())
        except Exception as exc:
            blocker_codes.append("queue_unavailable")
            return {
                "status": "unavailable",
                "error_code": _safe_error_code("queue", exc),
            }

        missing_or_unverified = [
            label for label in REQUIRED_QUEUE_LABELS if not _is_verified_queue(topology.get(label))
        ]
        executable_messages = {
            label: _safe_queue_count(topology.get(label)) for label in EXECUTABLE_QUEUE_LABELS
        }
        absent_queues = [
            label
            for label in REQUIRED_QUEUE_LABELS
            if _is_verified_absent_queue(topology.get(label))
        ]
        if missing_or_unverified:
            blocker_codes.append("queue_topology_incomplete")
        if any(count > 0 for count in executable_messages.values()):
            blocker_codes.append("runtime_queue_not_empty")
        return {
            "status": "incomplete" if missing_or_unverified else "ready",
            "scope": "all_runtime_messages",
            "topology": topology,
            "missing_or_unverified_queue_labels": missing_or_unverified,
            "verified_absent_queue_labels": absent_queues,
            "executable_messages_by_queue": executable_messages,
        }

    def _checkout_report(self, blocker_codes: list[str]) -> dict[str, object]:
        branch = str(self.checkout.get("branch") or "unknown")
        commit = str(self.checkout.get("commit") or "unknown")
        verified = (
            bool(self.checkout.get("verified")) and branch != "unknown" and commit != "unknown"
        )
        if not verified:
            blocker_codes.append("checkout_unverified")
        return {"verified": verified, "branch": branch, "commit": commit}

    def _coverage_report(
        self,
        *,
        database_ready: bool,
        queue_ready: bool,
        blocker_codes: list[str],
    ) -> dict[str, object]:
        expected = set(self.expected_environments or (self.target_environment,))
        verified = (
            {self.target_environment}
            if database_ready
            and queue_ready
            and self.target_environment
            and self.target_environment == self.observed_environment
            else set()
        )
        unverified = sorted(expected - verified)
        if self.target_environment != self.observed_environment:
            blocker_codes.append("target_environment_mismatch")
        if unverified:
            blocker_codes.append("environment_coverage_incomplete")
        return {
            "expected_environments": sorted(expected),
            "verified_environments": sorted(verified),
            "unverified_environments": unverified,
            "local_result_applies_only_to_target_environment": True,
        }

    def _runtime_configuration_report(
        self,
        database_report: Mapping[str, object],
        blocker_codes: list[str],
    ) -> dict[str, object]:
        environment_keys = sorted(
            key for key in TYPESCRIPT_RUNTIME_ENV_KEYS if str(self.environ.get(key) or "").strip()
        )
        database_keys = database_report.get("typescript_runtime_config_keys")
        if not isinstance(database_keys, list):
            database_keys = []
        if environment_keys:
            blocker_codes.append("typescript_environment_runtime_configuration")
        return {
            "environment_key_names": environment_keys,
            "database_keys": database_keys,
            "values_exposed": False,
        }


def _identifiers(
    rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
) -> list[dict[str, object]]:
    return [{field: row.get(field) for field in fields} for row in rows]


def _deduplicate(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _safe_queue_count(value: object) -> int:
    if not isinstance(value, Mapping):
        return 0
    count = value.get("messages")
    return int(count) if isinstance(count, int) and count >= 0 else 0


def _is_verified_queue(value: object) -> bool:
    if not isinstance(value, Mapping) or not isinstance(value.get("exists"), bool):
        return False
    messages = value.get("messages")
    consumers = value.get("consumers")
    valid_counts = (
        isinstance(messages, int)
        and messages >= 0
        and isinstance(consumers, int)
        and consumers >= 0
    )
    if not valid_counts:
        return False
    if value.get("exists") is False:
        return messages == 0 and consumers == 0
    return True


def _is_verified_absent_queue(value: object) -> bool:
    return _is_verified_queue(value) and isinstance(value, Mapping) and value.get("exists") is False


def _safe_error_code(boundary: str, error: Exception) -> str:
    return f"{boundary}_{type(error).__name__.lower()}"
