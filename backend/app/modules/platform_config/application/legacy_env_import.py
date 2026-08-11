from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.shared.exceptions import NonRetryableExecutionError

from ..infrastructure.repository import PlatformConfigRepository, json_text, now_iso
from .secrets import SecretProviderPort
from .validation import PlatformConfigValidationError, validate_code


_ENV_REF_RE = re.compile(r"^env:([A-Z_][A-Z0-9_]*)$")


@dataclass(frozen=True)
class LegacyEnvReferenceLocation:
    source_type: str
    entity_id: str
    field_path: str
    env_ref: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_type": self.source_type,
            "entity_id": self.entity_id,
            "field_path": self.field_path,
            "env_ref": self.env_ref,
        }


class LegacyEnvSecretImportService:
    """Explicitly migrate legacy env references without exposing env values."""

    def __init__(
        self,
        repository: PlatformConfigRepository,
        secret_provider: SecretProviderPort,
        *,
        read_environment: Callable[[str], str | None] | None = None,
    ) -> None:
        self.repository = repository
        self.secret_provider = secret_provider
        self._read_environment = read_environment or os.environ.get

    def report(self) -> dict[str, Any]:
        locations = self._scan()
        return self._report(locations)

    def import_reference(
        self,
        *,
        env_ref: str,
        code: str,
        actor_id: str,
        correlation_id: str = "",
        dry_run: bool,
        expected_digest: str = "",
    ) -> dict[str, Any]:
        env_name = self._validate_env_ref(env_ref)
        code = validate_code(code)
        target_ref = f"secret://platform/{code}"
        all_locations = self._scan()
        locations = [
            location
            for location in all_locations
            if location.env_ref == env_ref
        ]
        preview = self._report(locations)
        preview.update(
            {
                "env_ref": env_ref,
                "target_ref": target_ref,
                "dry_run": dry_run,
            }
        )
        if dry_run:
            return preview
        existing = self.repository.get_platform_secret_by_code(code)
        if existing:
            metadata = existing.get("metadata") or {}
            if (
                existing.get("ref") != target_ref
                or metadata.get("legacy_env_ref") != env_ref
            ):
                raise PlatformConfigValidationError(
                    f"Platform secret code is already used: {code}",
                    safe_message="目标凭据编码已被其他凭据使用",
                )
        if not locations:
            result = {
                **preview,
                "dry_run": False,
                "already_applied": bool(existing and existing.get("configured")),
                "rewritten": 0,
            }
            self._audit(
                actor_id=actor_id,
                correlation_id=correlation_id,
                env_ref=env_ref,
                target_ref=target_ref,
                action="import_noop",
                result=result,
            )
            return result
        if not expected_digest or expected_digest != preview["digest"]:
            raise PlatformConfigValidationError(
                "Legacy env import digest mismatch",
                safe_message="env 引用清单已变化，请重新执行 dry-run",
            )

        value = self._read_environment(env_name)
        if not value:
            raise NonRetryableExecutionError(
                f"Legacy env value is missing: {env_name}",
                safe_message="待导入的环境变量不存在或为空",
            )
        try:
            if not existing:
                self.secret_provider.create_secret(
                    code=code,
                    value=value,
                    purpose="legacy-env-import",
                    actor_id=actor_id,
                    metadata={"legacy_env_ref": env_ref},
                )
            rewritten = self._rewrite(
                env_ref=env_ref,
                target_ref=target_ref,
                locations=locations,
            )
        finally:
            value = ""
        result = {
            **preview,
            "dry_run": False,
            "already_applied": False,
            "rewritten": rewritten,
        }
        self._audit(
            actor_id=actor_id,
            correlation_id=correlation_id,
            env_ref=env_ref,
            target_ref=target_ref,
            action="import",
            result=result,
        )
        return result

    def _scan(self) -> list[LegacyEnvReferenceLocation]:
        locations: list[LegacyEnvReferenceLocation] = []
        self._scan_scalar(
            locations,
            table="platform_secret_reference",
            source_type="secret_reference",
            columns=("ref",),
        )
        self._scan_scalar(
            locations,
            table="platform_runtime_config_value",
            source_type="runtime_config",
            columns=("secret_ref",),
        )
        self._scan_scalar(
            locations,
            table="integration_connector",
            source_type="connector",
            columns=("secret_ref", "endpoint_ref"),
        )
        self._scan_json(
            locations,
            table="integration_connector",
            source_type="connector",
            column="metadata",
        )
        self._scan_json(
            locations,
            table="webhook_trigger_revision",
            source_type="webhook_draft",
            column="config_json",
            where="status <> 'published'",
        )
        return sorted(
            locations,
            key=lambda item: (
                item.env_ref,
                item.source_type,
                item.entity_id,
                item.field_path,
            ),
        )

    def _scan_scalar(
        self,
        locations: list[LegacyEnvReferenceLocation],
        *,
        table: str,
        source_type: str,
        columns: tuple[str, ...],
    ) -> None:
        rows = self.repository.database.execute(
            f"select id, {', '.join(columns)} from {table}"
        )
        for row in rows:
            for column in columns:
                value = str(row.get(column) or "")
                if _ENV_REF_RE.fullmatch(value):
                    locations.append(
                        LegacyEnvReferenceLocation(
                            source_type=source_type,
                            entity_id=str(row["id"]),
                            field_path=column,
                            env_ref=value,
                        )
                    )

    def _scan_json(
        self,
        locations: list[LegacyEnvReferenceLocation],
        *,
        table: str,
        source_type: str,
        column: str,
        where: str = "",
    ) -> None:
        where_sql = f" where {where}" if where else ""
        rows = self.repository.database.execute(
            f"select id, {column} from {table}{where_sql}"
        )
        for row in rows:
            try:
                payload = json.loads(str(row.get(column) or "{}"))
            except json.JSONDecodeError:
                continue
            for path, env_ref in _find_env_refs(payload):
                locations.append(
                    LegacyEnvReferenceLocation(
                        source_type=source_type,
                        entity_id=str(row["id"]),
                        field_path=f"{column}.{path}",
                        env_ref=env_ref,
                    )
                )

    def _rewrite(
        self,
        *,
        env_ref: str,
        target_ref: str,
        locations: list[LegacyEnvReferenceLocation],
    ) -> int:
        grouped: dict[tuple[str, str], list[LegacyEnvReferenceLocation]] = {}
        for location in locations:
            grouped.setdefault(
                (location.source_type, location.entity_id),
                [],
            ).append(location)
        rewritten = 0
        for (source_type, entity_id), items in grouped.items():
            if source_type == "secret_reference":
                self.repository.database.execute(
                    """
                    update platform_secret_reference
                    set provider = 'secret', ref = ?, revision = revision + 1,
                        updated_at = ?
                    where id = ? and ref = ?
                    """,
                    (target_ref, now_iso(), entity_id, env_ref),
                )
            elif source_type == "runtime_config":
                self.repository.database.execute(
                    """
                    update platform_runtime_config_value
                    set secret_ref = ?, revision = revision + 1, updated_at = ?
                    where id = ? and secret_ref = ?
                    """,
                    (target_ref, now_iso(), entity_id, env_ref),
                )
            elif source_type == "connector":
                scalar_fields = {
                    item.field_path
                    for item in items
                    if item.field_path in {"secret_ref", "endpoint_ref"}
                }
                for field in scalar_fields:
                    self.repository.database.execute(
                        f"""
                        update integration_connector
                        set {field} = ?, updated_at = ?
                        where id = ? and {field} = ?
                        """,
                        (target_ref, now_iso(), entity_id, env_ref),
                    )
                if any(item.field_path.startswith("metadata.") for item in items):
                    self._rewrite_json_column(
                        table="integration_connector",
                        column="metadata",
                        entity_id=entity_id,
                        env_ref=env_ref,
                        target_ref=target_ref,
                    )
            elif source_type == "webhook_draft":
                self._rewrite_webhook_draft(
                    entity_id=entity_id,
                    env_ref=env_ref,
                    target_ref=target_ref,
                )
            rewritten += len(items)
        return rewritten

    def _rewrite_json_column(
        self,
        *,
        table: str,
        column: str,
        entity_id: str,
        env_ref: str,
        target_ref: str,
        revisioned: bool = False,
    ) -> None:
        row = self.repository.database.execute_one(
            f"select {column} from {table} where id = ?",
            (entity_id,),
        )
        if not row:
            return
        payload = json.loads(str(row.get(column) or "{}"))
        updated, _ = _replace_env_ref(payload, env_ref, target_ref)
        revision_sql = ", revision = revision + 1" if revisioned else ""
        self.repository.database.execute(
            f"""
            update {table}
            set {column} = ?, updated_at = ?{revision_sql}
            where id = ?
            """,
            (json_text(updated), now_iso(), entity_id),
        )

    def _rewrite_webhook_draft(
        self,
        *,
        entity_id: str,
        env_ref: str,
        target_ref: str,
    ) -> None:
        row = self.repository.database.execute_one(
            """
            select config_json
            from webhook_trigger_revision
            where id = ? and status <> 'published'
            """,
            (entity_id,),
        )
        if not row:
            return
        payload = json.loads(str(row["config_json"]))
        updated, _ = _replace_env_ref(payload, env_ref, target_ref)
        encoded = json_text(updated)
        self.repository.database.execute(
            """
            update webhook_trigger_revision
            set config_json = ?, config_hash = ?, validation_json = '{}',
                status = 'draft', updated_at = ?
            where id = ?
            """,
            (
                encoded,
                hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                now_iso(),
                entity_id,
            ),
        )

    @staticmethod
    def _report(
        locations: list[LegacyEnvReferenceLocation],
    ) -> dict[str, Any]:
        items = [location.to_dict() for location in locations]
        encoded = json.dumps(
            items,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "count": len(items),
            "references": items,
            "digest": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _validate_env_ref(env_ref: str) -> str:
        match = _ENV_REF_RE.fullmatch(str(env_ref or "").strip())
        if not match:
            raise PlatformConfigValidationError(
                "Invalid legacy env secret reference",
                safe_message="旧 env 凭据引用格式无效",
            )
        return match.group(1)

    def _audit(
        self,
        *,
        actor_id: str,
        correlation_id: str,
        env_ref: str,
        target_ref: str,
        action: str,
        result: dict[str, Any],
    ) -> None:
        self.repository.record_config_audit(
            entity_type="legacy_env_secret_import",
            entity_id=env_ref,
            action=action,
            actor_id=actor_id,
            before={"env_ref": env_ref, "digest": result["digest"]},
            after={
                "target_ref": target_ref,
                "rewritten": int(result.get("rewritten") or 0),
                "already_applied": bool(result.get("already_applied")),
            },
            correlation_id=correlation_id,
        )


def _find_env_refs(value: Any, *, path: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in sorted(value.items(), key=lambda item: str(item[0])):
            child_path = f"{path}.{key}" if path else str(key)
            found.extend(_find_env_refs(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            found.extend(_find_env_refs(child, path=child_path))
    elif isinstance(value, str) and _ENV_REF_RE.fullmatch(value):
        found.append((path, value))
    return found


def _replace_env_ref(
    value: Any,
    env_ref: str,
    target_ref: str,
) -> tuple[Any, int]:
    if isinstance(value, dict):
        count = 0
        updated: dict[str, Any] = {}
        for key, child in value.items():
            replacement, child_count = _replace_env_ref(
                child,
                env_ref,
                target_ref,
            )
            updated[str(key)] = replacement
            count += child_count
        return updated, count
    if isinstance(value, list):
        count = 0
        updated_list: list[Any] = []
        for child in value:
            replacement, child_count = _replace_env_ref(
                child,
                env_ref,
                target_ref,
            )
            updated_list.append(replacement)
            count += child_count
        return updated_list, count
    if value == env_ref:
        return target_ref, 1
    return value, 0
