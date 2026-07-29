from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

from app.modules.platform_config.application.validation import (
    PlatformConfigValidationError,
    validate_secret_ref,
)


@dataclass(frozen=True)
class CanonicalProviderDocument:
    provider_type: str
    contract_version: str
    resource_kind: str
    config: dict[str, Any]
    secret_refs: dict[str, str]


@dataclass(frozen=True)
class ProviderContract:
    provider_type: str
    contract_version: str
    resource_kind: str
    available: bool
    fields: tuple[dict[str, Any], ...]
    unavailable_reason: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "provider_type": self.provider_type,
            "contract_version": self.contract_version,
            "resource_kind": self.resource_kind,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "fields": [dict(item) for item in self.fields],
            },
        }


_DATABASE_COMMON_FIELDS = (
    {"name": "host", "type": "string", "required": True},
    {"name": "port", "type": "integer", "required": True, "minimum": 1, "maximum": 65535},
    {"name": "database", "type": "string", "required": True},
    {"name": "username", "type": "string", "required": True},
    {"name": "password_ref", "type": "secret_ref", "required": True},
    {"name": "schema", "type": "string", "required": False},
)

_CONTRACTS = {
    "mysql": ProviderContract(
        provider_type="mysql",
        contract_version="mysql_v1",
        resource_kind="database",
        available=True,
        fields=_DATABASE_COMMON_FIELDS,
    ),
    "sqlserver": ProviderContract(
        provider_type="sqlserver",
        contract_version="sqlserver_v1",
        resource_kind="database",
        available=True,
        fields=_DATABASE_COMMON_FIELDS,
    ),
    "oracle": ProviderContract(
        provider_type="oracle",
        contract_version="oracle_11g_v1",
        resource_kind="database",
        available=True,
        fields=(
            {"name": "host", "type": "string", "required": True},
            {
                "name": "port",
                "type": "integer",
                "required": True,
                "minimum": 1,
                "maximum": 65535,
            },
            {"name": "service_name", "type": "string", "required": False},
            {"name": "sid", "type": "string", "required": False},
            {"name": "username", "type": "string", "required": True},
            {"name": "password_ref", "type": "secret_ref", "required": True},
            {"name": "schema", "type": "string", "required": False},
        ),
    ),
    "redis": ProviderContract(
        provider_type="redis",
        contract_version="redis_v1",
        resource_kind="redis",
        available=True,
        fields=(
            {"name": "host", "type": "string", "required": True},
            {
                "name": "port",
                "type": "integer",
                "required": True,
                "minimum": 1,
                "maximum": 65535,
            },
            {
                "name": "database",
                "type": "integer",
                "required": True,
                "minimum": 0,
                "maximum": 15,
            },
            {"name": "username", "type": "string", "required": False},
            {"name": "password_ref", "type": "secret_ref", "required": False},
            {"name": "tls", "type": "tls", "required": False},
        ),
    ),
    "loki": ProviderContract(
        provider_type="loki",
        contract_version="loki_v1",
        resource_kind="loki",
        available=True,
        fields=(
            {"name": "base_url", "type": "url", "required": True},
            {"name": "tenant_id", "type": "string", "required": False},
            {"name": "auth_ref", "type": "secret_ref", "required": False},
            {
                "name": "timeout_seconds",
                "type": "integer",
                "required": True,
                "minimum": 1,
                "maximum": 60,
            },
            {
                "name": "max_minutes",
                "type": "integer",
                "required": True,
                "minimum": 1,
                "maximum": 1440,
            },
            {
                "name": "max_lines",
                "type": "integer",
                "required": True,
                "minimum": 1,
                "maximum": 5000,
            },
            {
                "name": "max_response_bytes",
                "type": "integer",
                "required": True,
                "minimum": 1024,
                "maximum": 10485760,
            },
        ),
    ),
    "postgresql": ProviderContract(
        provider_type="postgresql",
        contract_version="postgresql_unavailable_v1",
        resource_kind="database",
        available=False,
        fields=_DATABASE_COMMON_FIELDS,
        unavailable_reason="尚未安装 PostgreSQL 业务数据运行时 Handler",
    ),
}


class ProviderContractRegistry:
    def public_contracts(self) -> list[dict[str, Any]]:
        return [
            _CONTRACTS[key].public()
            for key in sorted(_CONTRACTS)
        ]

    def require(self, provider_type: str) -> ProviderContract:
        normalized = str(provider_type or "").strip().lower()
        contract = _CONTRACTS.get(normalized)
        if not contract:
            raise PlatformConfigValidationError(
                f"Unknown Resource Provider: {normalized}",
                safe_message="工具资源 Provider 无效",
                error_code="resource_provider_invalid",
            )
        if not contract.available:
            raise PlatformConfigValidationError(
                f"Resource Provider is unavailable: {normalized}",
                safe_message=contract.unavailable_reason,
                error_code="resource_provider_unavailable",
            )
        return contract

    def normalize(
        self,
        *,
        provider_type: str,
        config: dict[str, Any],
        secret_refs: dict[str, str] | None = None,
        import_legacy: bool = False,
    ) -> CanonicalProviderDocument:
        contract = self.require(provider_type)
        normalized_config = dict(config)
        normalized_refs = dict(secret_refs or {})
        self._extract_secret_fields(
            normalized_config,
            normalized_refs,
            contract=contract,
            import_legacy=import_legacy,
        )
        if contract.resource_kind == "database":
            canonical = self._database(
                contract,
                normalized_config,
                import_legacy=import_legacy,
            )
        elif contract.resource_kind == "redis":
            canonical = self._redis(
                normalized_config,
                import_legacy=import_legacy,
            )
        else:
            canonical = self._loki(
                normalized_config,
                import_legacy=import_legacy,
            )
        allowed_refs = {
            str(field["name"])
            for field in contract.fields
            if field["type"] == "secret_ref"
        }
        unknown_refs = sorted(set(normalized_refs).difference(allowed_refs))
        if unknown_refs:
            raise self._field_error(
                f"Unknown Secret reference fields: {unknown_refs}"
            )
        canonical_refs = {
            key: validate_secret_ref(str(value))
            for key, value in normalized_refs.items()
            if str(value or "").strip()
        }
        for field in contract.fields:
            if (
                field["type"] == "secret_ref"
                and field["required"]
                and field["name"] not in canonical_refs
            ):
                raise self._field_error(
                    f"Missing required field: {field['name']}"
                )
        return CanonicalProviderDocument(
            provider_type=contract.provider_type,
            contract_version=contract.contract_version,
            resource_kind=contract.resource_kind,
            config=canonical,
            secret_refs=canonical_refs,
        )

    def runtime_projection(
        self,
        document: CanonicalProviderDocument,
        *,
        resolve_secret: Callable[[str], str],
    ) -> dict[str, Any]:
        projected = dict(document.config)
        for key, ref in document.secret_refs.items():
            runtime_key = {
                "password_ref": "password",
                "auth_ref": "auth_token",
            }.get(key, key.removesuffix("_ref"))
            projected[runtime_key] = resolve_secret(ref)
        if document.resource_kind == "database":
            projected["user"] = projected.pop("username")
        elif document.resource_kind == "redis":
            projected["db"] = projected.pop("database")
        elif document.resource_kind == "loki":
            projected["tenant"] = projected.pop("tenant_id", "")
        return projected

    def _database(
        self,
        contract: ProviderContract,
        config: dict[str, Any],
        *,
        import_legacy: bool,
    ) -> dict[str, Any]:
        if import_legacy:
            self._rename(config, "user", "username")
            if contract.provider_type == "oracle":
                self._rename(config, "database", "service_name")
                use_sid = bool(config.pop("use_sid", False))
                if use_sid and "service_name" in config:
                    config["sid"] = config.pop("service_name")
                config.pop("oracle_client_mode", None)
                config.pop("oracle_compat", None)
        aliases = {"user", "connect_descriptor", "use_sid", "oracle_client_mode", "oracle_compat"}
        if any(key in config for key in aliases):
            raise self._field_error(
                "Legacy or unsafe database fields require explicit import"
            )
        allowed = {
            str(field["name"])
            for field in contract.fields
            if field["type"] != "secret_ref"
        }
        self._reject_unknown(config, allowed)
        required = {"host", "port", "username"}
        if contract.provider_type == "oracle":
            service_name = self._text(config.get("service_name"))
            sid = self._text(config.get("sid"))
            if bool(service_name) == bool(sid):
                raise self._field_error(
                    "Oracle requires exactly one of service_name or sid"
                )
        else:
            required.add("database")
        self._require_fields(config, required)
        canonical = {
            key: value
            for key, value in config.items()
            if value not in {None, ""}
        }
        canonical["host"] = self._text(config["host"])
        canonical["port"] = self._port(config["port"])
        canonical["username"] = self._text(config["username"])
        for key in ("database", "service_name", "sid", "schema"):
            if key in canonical:
                canonical[key] = self._text(canonical[key])
        return canonical

    def _redis(
        self,
        config: dict[str, Any],
        *,
        import_legacy: bool,
    ) -> dict[str, Any]:
        if import_legacy:
            self._rename(config, "db", "database")
            self._rename(config, "user", "username")
            mode = str(config.pop("mode", "standalone") or "standalone")
            if mode != "standalone" or config.pop("nodes", None):
                raise self._field_error(
                    "Redis cluster import requires manual canonical conversion"
                )
        if any(key in config for key in ("db", "user", "mode", "nodes")):
            raise self._field_error(
                "Redis db/user/mode/nodes are not canonical fields"
            )
        allowed = {"host", "port", "database", "username", "tls"}
        self._reject_unknown(config, allowed)
        self._require_fields(config, {"host", "port", "database"})
        database = self._integer(
            config["database"],
            field="database",
            minimum=0,
            maximum=15,
        )
        tls = config.get("tls") or {"enabled": False}
        if not isinstance(tls, dict):
            raise self._field_error("Redis tls must be an object")
        self._reject_unknown(tls, {"enabled", "verify_certificate"})
        canonical_tls = {
            "enabled": self._boolean(
                tls.get("enabled", False),
                field="tls.enabled",
            ),
            "verify_certificate": self._boolean(
                tls.get("verify_certificate", True),
                field="tls.verify_certificate",
            ),
        }
        return {
            "host": self._text(config["host"]),
            "port": self._port(config["port"]),
            "database": database,
            "username": self._text(config.get("username")),
            "tls": canonical_tls,
        }

    def _loki(
        self,
        config: dict[str, Any],
        *,
        import_legacy: bool,
    ) -> dict[str, Any]:
        if import_legacy:
            self._rename(config, "tenant", "tenant_id")
        if "tenant" in config:
            raise self._field_error(
                "Loki tenant is not canonical; use tenant_id"
            )
        allowed = {
            "base_url",
            "tenant_id",
            "timeout_seconds",
            "max_minutes",
            "max_lines",
            "max_response_bytes",
        }
        self._reject_unknown(config, allowed)
        self._require_fields(
            config,
            {
                "base_url",
                "timeout_seconds",
                "max_minutes",
                "max_lines",
                "max_response_bytes",
            },
        )
        base_url = self._text(config["base_url"])
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise self._field_error("Loki base_url must be an HTTP(S) URL")
        return {
            "base_url": base_url.rstrip("/"),
            "tenant_id": self._text(config.get("tenant_id")),
            "timeout_seconds": self._integer(
                config["timeout_seconds"],
                field="timeout_seconds",
                minimum=1,
                maximum=60,
            ),
            "max_minutes": self._integer(
                config["max_minutes"],
                field="max_minutes",
                minimum=1,
                maximum=1440,
            ),
            "max_lines": self._integer(
                config["max_lines"],
                field="max_lines",
                minimum=1,
                maximum=5000,
            ),
            "max_response_bytes": self._integer(
                config["max_response_bytes"],
                field="max_response_bytes",
                minimum=1024,
                maximum=10485760,
            ),
        }

    def _extract_secret_fields(
        self,
        config: dict[str, Any],
        secret_refs: dict[str, str],
        *,
        contract: ProviderContract,
        import_legacy: bool,
    ) -> None:
        if import_legacy:
            self._rename(secret_refs, "password", "password_ref")
            self._rename(secret_refs, "auth", "auth_ref")
        for field in contract.fields:
            if field["type"] != "secret_ref":
                continue
            name = str(field["name"])
            if name in config:
                if name in secret_refs:
                    raise self._field_error(
                        f"Duplicate Secret reference field: {name}"
                    )
                secret_refs[name] = str(config.pop(name))

    @staticmethod
    def _rename(value: dict[str, Any], old: str, new: str) -> None:
        if old not in value:
            return
        if new in value:
            raise ProviderContractRegistry._field_error(
                f"Both legacy {old} and canonical {new} were provided"
            )
        value[new] = value.pop(old)

    @staticmethod
    def _reject_unknown(
        value: dict[str, Any],
        allowed: set[str],
    ) -> None:
        unknown = sorted(set(value).difference(allowed))
        if unknown:
            raise ProviderContractRegistry._field_error(
                f"Unknown Provider fields: {unknown}"
            )

    @staticmethod
    def _require_fields(value: dict[str, Any], required: set[str]) -> None:
        missing = sorted(
            key
            for key in required
            if value.get(key) is None or str(value.get(key)).strip() == ""
        )
        if missing:
            raise ProviderContractRegistry._field_error(
                f"Missing required Provider fields: {missing}"
            )

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _port(value: Any) -> int:
        return ProviderContractRegistry._integer(
            value,
            field="port",
            minimum=1,
            maximum=65535,
        )

    @staticmethod
    def _integer(
        value: Any,
        *,
        field: str,
        minimum: int,
        maximum: int,
    ) -> int:
        if isinstance(value, bool):
            raise ProviderContractRegistry._field_error(
                f"{field} must be an integer"
            )
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ProviderContractRegistry._field_error(
                f"{field} must be an integer"
            ) from exc
        if result < minimum or result > maximum:
            raise ProviderContractRegistry._field_error(
                f"{field} is outside allowed bounds"
            )
        return result

    @staticmethod
    def _boolean(value: Any, *, field: str) -> bool:
        if not isinstance(value, bool):
            raise ProviderContractRegistry._field_error(
                f"{field} must be a boolean"
            )
        return value

    @staticmethod
    def _field_error(message: str) -> PlatformConfigValidationError:
        return PlatformConfigValidationError(
            message,
            safe_message="工具资源 Provider 字段无效",
            error_code="resource_provider_contract_invalid",
        )
