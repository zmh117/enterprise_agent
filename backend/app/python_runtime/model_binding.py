from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.modules.model_connection.domain import ModelRuntimeBinding
from app.modules.platform_config.application.secrets import EncryptedDbSecretProvider
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


@dataclass(frozen=True)
class ResolvedPythonModelBinding:
    binding: ModelRuntimeBinding
    api_key: str


class PythonModelBindingResolver:
    """Read one frozen model revision and decrypt only its active credential."""

    def __init__(
        self,
        database: Database,
        *,
        master_key: str,
        allowed_hosts: tuple[str, ...],
    ) -> None:
        self._database = database
        platform = PlatformConfigRepository(database)
        self._secrets = EncryptedDbSecretProvider(platform, master_key=master_key)
        self._allowed_hosts = frozenset(host.lower() for host in allowed_hosts if host)

    def resolve(self, revision_id: str, config_hash: str) -> ResolvedPythonModelBinding:
        revision = self._database.execute_one(
            """
            select r.id revision_id, r.connection_id, r.status revision_status,
                   r.config_json, r.config_hash, r.api_key_secret_id,
                   c.protocol connection_protocol, c.status connection_status,
                   s.id secret_id, s.provider secret_provider,
                   s.status secret_status, s.active_version,
                   v.ciphertext, v.nonce, v.key_id, v.algorithm,
                   v.status version_status
              from model_connection_revision r
              join model_connection c on c.id = r.connection_id
              join platform_secret s on s.id = r.api_key_secret_id
              join platform_secret_version v
                on v.secret_id = s.id and v.version = s.active_version
             where r.id = ?
            """,
            (revision_id,),
        )
        if revision is None:
            raise NonRetryableExecutionError(
                "Frozen model connection revision is unavailable",
                safe_message="模型连接版本不可用",
                error_code="model_connection_credential_unavailable",
            )
        try:
            parsed = json.loads(str(revision["config_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise NonRetryableExecutionError(
                "Model connection revision config is invalid",
                safe_message="模型连接配置不完整",
                error_code="model_connection_integrity_failed",
            ) from exc
        if not isinstance(parsed, dict):
            raise NonRetryableExecutionError(
                "Model connection revision config is invalid",
                safe_message="模型连接配置不完整",
                error_code="model_connection_integrity_failed",
            )
        config = dict(parsed)
        actual_hash = hashlib.sha256(
            json.dumps(
                config,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if actual_hash != str(revision["config_hash"]) or actual_hash != config_hash:
            raise NonRetryableExecutionError(
                "Model connection revision hash mismatch",
                safe_message="模型连接完整性校验失败",
                error_code="model_connection_integrity_failed",
            )
        if (
            str(revision.get("revision_status")) != "ready"
            or str(revision.get("connection_status")) != "ready"
            or str(revision.get("connection_protocol")) != "anthropic_compatible"
            or str(revision.get("secret_provider")) != "encrypted_db"
            or str(revision.get("secret_status")) != "enabled"
            or str(revision.get("version_status")) != "active"
            or str(revision.get("api_key_secret_id")) != str(revision.get("secret_id"))
        ):
            raise NonRetryableExecutionError(
                "Model connection revision is not ready",
                safe_message="模型连接尚未就绪",
                error_code="model_connection_rotation_required",
            )
        required = {
            "protocol",
            "base_url",
            "model",
            "default_opus_model",
            "default_sonnet_model",
            "default_haiku_model",
            "subagent_model",
            "effort_level",
        }
        if not required.issubset(config):
            raise NonRetryableExecutionError(
                "Model connection revision is incomplete",
                safe_message="模型连接配置不完整",
                error_code="model_connection_integrity_failed",
            )
        provider_host = (urlsplit(str(config["base_url"])).hostname or "").lower()
        if provider_host not in self._allowed_hosts:
            raise NonRetryableExecutionError(
                "Model provider host is outside the Runtime allowlist",
                safe_message="模型服务地址不受支持",
                error_code="model_connection_host_not_allowed",
            )
        secret_id = str(revision.get("secret_id") or "")
        if not secret_id:
            raise NonRetryableExecutionError(
                "Model connection credential is missing",
                safe_message="模型连接凭据缺失",
                error_code="model_connection_credential_unavailable",
            )
        active_version = int(revision.get("active_version") or 0)
        if active_version < 1:
            raise NonRetryableExecutionError(
                "Model connection credential version is invalid",
                safe_message="模型连接凭据缺失",
                error_code="model_connection_credential_unavailable",
            )
        api_key = self._secrets.decrypt_persisted_version(
            ciphertext=str(revision["ciphertext"]),
            nonce=str(revision["nonce"]),
            key_id=str(revision["key_id"]),
            algorithm=str(revision["algorithm"]),
            secret_id=secret_id,
            version=active_version,
        )
        binding = ModelRuntimeBinding(
            protocol=str(config["protocol"]),
            base_url=str(config["base_url"]),
            model=str(config["model"]),
            default_opus_model=str(config["default_opus_model"]),
            default_sonnet_model=str(config["default_sonnet_model"]),
            default_haiku_model=str(config["default_haiku_model"]),
            subagent_model=str(config["subagent_model"]),
            effort_level=str(config["effort_level"]),
            connection_id=str(revision["connection_id"]),
            connection_code="",
            connection_revision_id=str(revision["revision_id"]),
            connection_revision=0,
            config_hash=actual_hash,
            secret_ref="",
        )
        return ResolvedPythonModelBinding(binding=binding, api_key=api_key)
