from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from app.modules.admin.domain.providers import TOOL_PROVIDERS
from app.shared.exceptions import NonRetryableExecutionError


FORBIDDEN_KEYS = {
    "password",
    "token",
    "secret",
    "api_key",
    "script",
    "shell",
    "command",
    "method",
    "http_url",
}


class ResourceProviderService:
    def catalog(self) -> list[dict[str, Any]]:
        return [dict(item) for item in TOOL_PROVIDERS]

    def validate(self, payload: dict[str, Any]) -> None:
        kind = str(payload.get("resource_kind") or "")
        provider = next((item for item in TOOL_PROVIDERS if item["code"] == kind), None)
        if provider is None or not provider["available"]:
            raise _invalid("resource_kind", "Unsupported resource provider")
        engine = str(payload.get("engine") or "")
        if kind == "database" and engine not in provider["dialects"]:
            raise _invalid("engine", "Database dialect is not available")
        config = payload.get("config")
        if not isinstance(config, dict):
            raise _invalid("config", "Configuration must be an object")
        forbidden = sorted(key for key in config if key.lower() in FORBIDDEN_KEYS)
        if forbidden:
            raise _invalid(
                f"config.{forbidden[0]}",
                "Plaintext credentials and executable definitions are forbidden",
            )
        required = provider["config_schema"]["required"]
        for field in required:
            value = config.get(field)
            if value is None or value == "" or value == () or value == []:
                raise _invalid(f"config.{field}", "Field is required")
        host = self._host(kind, config)
        allowlist = config.get("host_allowlist")
        if not isinstance(allowlist, list) or host not in {str(value) for value in allowlist}:
            raise _invalid("config.host_allowlist", "Target host must be explicitly allowlisted")

    def probe(
        self,
        resource: dict[str, Any],
        resolve_secret: Callable[[str], str],
    ) -> dict[str, Any]:
        self.validate(resource)
        started = time.monotonic()
        kind = str(resource["resource_kind"])
        try:
            if kind == "database":
                self._probe_database(resource, resolve_secret)
            elif kind == "redis":
                self._probe_redis(resource, resolve_secret)
            else:
                self._probe_loki(resource, resolve_secret)
        except Exception as exc:
            raise NonRetryableExecutionError(
                f"Resource probe failed: {type(exc).__name__}",
                safe_message="Connection test failed",
                error_code="connection_test_failed",
            ) from exc
        return {
            "resource_kind": kind,
            "status": "succeeded",
            "duration_ms": max(1, int((time.monotonic() - started) * 1000)),
            "summary": "Read-only connectivity probe succeeded",
        }

    @staticmethod
    def _host(kind: str, config: dict[str, Any]) -> str:
        if kind == "loki":
            parsed = urlparse(str(config.get("base_url") or ""))
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise _invalid("config.base_url", "Loki URL must use http or https")
            return parsed.hostname
        return str(config.get("host") or "")

    @staticmethod
    def _secret(resource: dict[str, Any], key: str, resolver: Callable[[str], str]) -> str:
        refs = resource.get("secret_refs") or {}
        ref = str(refs.get(key) or "") if isinstance(refs, dict) else ""
        return resolver(ref) if ref else ""

    def _probe_database(self, resource: dict[str, Any], resolver: Callable[[str], str]) -> None:
        config = resource["config"]
        engine = str(resource["engine"])
        password = self._secret(resource, "password", resolver)
        if engine == "postgresql":
            import psycopg

            with psycopg.connect(
                host=config["host"],
                port=int(config["port"]),
                dbname=config["database"],
                user=config["username"],
                password=password,
                connect_timeout=2,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
        elif engine == "mysql":
            import pymysql

            connection = pymysql.connect(
                host=config["host"],
                port=int(config["port"]),
                database=config["database"],
                user=config["username"],
                password=password,
                connect_timeout=2,
                read_timeout=2,
                write_timeout=2,
            )
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            finally:
                connection.close()
        else:
            import pyodbc

            connection = pyodbc.connect(
                "DRIVER={ODBC Driver 18 for SQL Server};"
                f"SERVER={config['host']},{int(config['port'])};DATABASE={config['database']};"
                f"UID={config['username']};PWD={password};Encrypt=yes;TrustServerCertificate=yes;",
                timeout=2,
            )
            try:
                connection.cursor().execute("SELECT 1").fetchone()
            finally:
                connection.close()

    def _probe_redis(self, resource: dict[str, Any], resolver: Callable[[str], str]) -> None:
        import redis

        config = resource["config"]
        client = redis.Redis(
            host=config["host"],
            port=int(config["port"]),
            db=int(config.get("database") or 0),
            username=config.get("username") or None,
            password=self._secret(resource, "password", resolver) or None,
            ssl=bool(config.get("tls")),
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()

    def _probe_loki(self, resource: dict[str, Any], resolver: Callable[[str], str]) -> None:
        config = resource["config"]
        headers = {"Accept": "text/plain"}
        token = self._secret(resource, "token", resolver)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        tenant = str(config.get("tenant_id") or "")
        if tenant:
            headers["X-Scope-OrgID"] = tenant
        with urlopen(
            Request(urljoin(str(config["base_url"]).rstrip("/") + "/", "ready"), headers=headers),
            timeout=2,
        ) as response:
            if response.status >= 400:
                raise RuntimeError("Loki is not ready")
            response.read(1024)


def _invalid(field: str, message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Invalid tool resource",
        safe_message="Tool resource configuration is invalid",
        error_code="validation_failed",
        field_errors=[{"field": field, "message": message}],
    )
