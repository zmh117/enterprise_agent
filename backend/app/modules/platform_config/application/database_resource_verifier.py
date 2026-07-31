from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any, Protocol
import urllib.error
from urllib.request import Request, urlopen

from app.modules.platform_config.domain.provider_contracts import (
    ProviderContractRegistry,
)
from app.shared.database import assert_external_io_allowed

from .governed_resources import ResourceVerificationOutcome


class ReadonlyAccountViolation(RuntimeError):
    """The configured account has effective write or administrative privileges."""


class DatabaseReadonlyProbe(Protocol):
    def verify(
        self,
        config: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


_MYSQL_ALLOWED_PRIVILEGES = frozenset(
    {
        "SELECT",
        "SHOW VIEW",
        "USAGE",
    }
)


class MysqlReadonlyAccountProbe:
    def __init__(
        self,
        connect_factory: Callable[..., Any] | None = None,
        *,
        allow_privileged_account: bool = False,
    ) -> None:
        self._connect_factory = connect_factory
        self._allow_privileged_account = allow_privileged_account

    def verify(
        self,
        config: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        assert_external_io_allowed("resource_verify.mysql")
        connect = self._connect_factory
        if connect is None:
            import pymysql

            connect = pymysql.connect
        connection = connect(
            host=config["host"],
            port=int(config["port"]),
            user=config["user"],
            password=config["password"],
            database=config["database"],
            connect_timeout=timeout_seconds,
            read_timeout=timeout_seconds,
            write_timeout=timeout_seconds,
            autocommit=False,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW GRANTS FOR CURRENT_USER")
                grant_rows = list(cursor.fetchall())
                grants = [
                    str(row[0] if isinstance(row, (tuple, list)) else next(iter(row.values())))
                    for row in grant_rows
                ]
                readonly_account = True
                try:
                    self._assert_grants_readonly(grants)
                except ReadonlyAccountViolation:
                    if not self._allow_privileged_account:
                        raise
                    readonly_account = False
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
                cursor.execute(
                    f"SET SESSION MAX_EXECUTION_TIME = {timeout_seconds * 1000}"
                )
                cursor.execute("START TRANSACTION READ ONLY")
                cursor.execute("SELECT 1")
                cursor.fetchone()
            connection.rollback()
            return {
                "connection": True,
                "readonly_account": readonly_account,
                "privileged_account_allowed": not readonly_account,
                "readonly_session": True,
                "grant_count": len(grants),
            }
        finally:
            connection.close()

    @staticmethod
    def _assert_grants_readonly(grants: list[str]) -> None:
        if not grants:
            raise ReadonlyAccountViolation("MySQL grants are unavailable")
        for statement in grants:
            normalized = " ".join(statement.upper().split())
            if not normalized.startswith("GRANT ") or " ON " not in normalized:
                raise ReadonlyAccountViolation(
                    "MySQL role or non-canonical grant requires manual review"
                )
            privilege_text = normalized.removeprefix("GRANT ").split(" ON ", 1)[0]
            privileges = {
                privilege.strip().split(" (", 1)[0]
                for privilege in privilege_text.split(",")
            }
            if not privileges or not privileges.issubset(
                _MYSQL_ALLOWED_PRIVILEGES
            ):
                raise ReadonlyAccountViolation(
                    "MySQL account has non-readonly privileges"
                )
            if " WITH GRANT OPTION" in normalized:
                raise ReadonlyAccountViolation(
                    "MySQL account has GRANT OPTION"
                )


_SQLSERVER_DANGEROUS_SERVER_ROLES = (
    "sysadmin",
    "serveradmin",
    "securityadmin",
    "setupadmin",
    "processadmin",
    "diskadmin",
    "dbcreator",
    "bulkadmin",
)
_SQLSERVER_DANGEROUS_DATABASE_ROLES = (
    "db_owner",
    "db_datawriter",
    "db_ddladmin",
    "db_accessadmin",
    "db_securityadmin",
    "db_backupoperator",
)
_SQLSERVER_ALLOWED_DATABASE_PERMISSIONS = frozenset(
    {
        "CONNECT",
        "SELECT",
        "VIEW CHANGE TRACKING",
        "VIEW DATABASE STATE",
        "VIEW DEFINITION",
    }
)


class SqlServerReadonlyAccountProbe:
    def __init__(
        self,
        connect_factory: Callable[..., Any] | None = None,
        *,
        allow_privileged_account: bool = False,
    ) -> None:
        self._connect_factory = connect_factory
        self._allow_privileged_account = allow_privileged_account

    def verify(
        self,
        config: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        assert_external_io_allowed("resource_verify.sqlserver")
        connect = self._connect_factory
        if connect is None:
            import pymssql

            connect = pymssql.connect
        connection = connect(
            server=config["host"],
            port=str(config["port"]),
            user=config["user"],
            password=config["password"],
            database=config["database"],
            login_timeout=timeout_seconds,
            timeout=timeout_seconds,
        )
        try:
            cursor = connection.cursor()
            try:
                dangerous_roles = (
                    _SQLSERVER_DANGEROUS_SERVER_ROLES
                    + _SQLSERVER_DANGEROUS_DATABASE_ROLES
                )
                role_checks = ", ".join(
                    (
                        f"IS_SRVROLEMEMBER('{role}')"
                        if role in _SQLSERVER_DANGEROUS_SERVER_ROLES
                        else f"IS_MEMBER('{role}')"
                    )
                    for role in dangerous_roles
                )
                cursor.execute(f"SELECT {role_checks}")
                membership = cursor.fetchone() or ()
                cursor.execute(
                    "SELECT permission_name "
                    "FROM fn_my_permissions(NULL, 'DATABASE')"
                )
                permission_rows = list(cursor.fetchall())
                permissions = {
                    str(
                        row[0]
                        if isinstance(row, (tuple, list))
                        else next(iter(row.values()))
                    ).upper()
                    for row in permission_rows
                }
                readonly_account = (
                    not any(value == 1 for value in membership)
                    and permissions.issubset(
                        _SQLSERVER_ALLOWED_DATABASE_PERMISSIONS
                    )
                )
                if (
                    not readonly_account
                    and not self._allow_privileged_account
                ):
                    raise ReadonlyAccountViolation(
                        "SQL Server account has a privileged role "
                        "or non-readonly permissions"
                    )
                cursor.execute(f"SET LOCK_TIMEOUT {timeout_seconds * 1000}")
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return {
                    "connection": True,
                    "readonly_account": readonly_account,
                    "privileged_account_allowed": not readonly_account,
                    "timeout_guard": True,
                    "permission_count": len(permissions),
                }
            finally:
                close = getattr(cursor, "close", None)
                if close is not None:
                    close()
        finally:
            connection.close()


_ORACLE_ALLOWED_SYSTEM_PRIVILEGES = frozenset(
    {
        "CREATE SESSION",
        "SELECT ANY DICTIONARY",
        "SELECT ANY TABLE",
    }
)
_ORACLE_ALLOWED_OBJECT_PRIVILEGES = frozenset({"READ", "SELECT"})
_ORACLE_ALLOWED_ROLES = frozenset({"CONNECT", "SELECT_CATALOG_ROLE"})


class Oracle11gReadonlyAccountProbe:
    def __init__(
        self,
        *,
        oracledb_module: Any | None = None,
        client_ready: Callable[[], None] | None = None,
        allow_privileged_account: bool = False,
    ) -> None:
        self._oracledb_module = oracledb_module
        self._client_ready = client_ready
        self._allow_privileged_account = allow_privileged_account

    def verify(
        self,
        config: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        assert_external_io_allowed("resource_verify.oracle")
        if self._client_ready is None:
            from app.modules.internal_api_platform.domain.topology import (
                OracleClientMode,
            )
            from app.modules.internal_api_platform.infrastructure.db.oracle_client import (
                assert_oracle_client_mode_ready,
            )

            assert_oracle_client_mode_ready(OracleClientMode.THICK)
        else:
            self._client_ready()
        oracledb = self._oracledb_module
        if oracledb is None:
            import oracledb as imported_oracledb

            oracledb = imported_oracledb
        if bool(oracledb.is_thin_mode()):
            raise ReadonlyAccountViolation(
                "python-oracledb is not using Thick mode"
            )
        service_name = str(config.get("service_name") or "").strip()
        sid = str(config.get("sid") or "").strip()
        if bool(service_name) == bool(sid):
            raise ReadonlyAccountViolation(
                "Oracle requires exactly one Service Name or SID"
            )
        dsn = (
            oracledb.makedsn(
                config["host"],
                int(config["port"]),
                service_name=service_name,
            )
            if service_name
            else oracledb.makedsn(
                config["host"],
                int(config["port"]),
                sid=sid,
            )
        )
        connection = oracledb.connect(
            user=config["user"],
            password=config["password"],
            dsn=dsn,
        )
        try:
            connection.call_timeout = timeout_seconds * 1000
            version = str(getattr(connection, "version", "") or "")
            if not version.startswith("11.2.0.4"):
                raise ReadonlyAccountViolation(
                    "Oracle server is not 11.2.0.4"
                )
            cursor = connection.cursor()
            try:
                schema = str(config.get("schema") or "").strip()
                if schema:
                    if not schema.replace("_", "").isalnum():
                        raise ReadonlyAccountViolation(
                            "Oracle schema is invalid"
                        )
                    cursor.execute(
                        f'ALTER SESSION SET CURRENT_SCHEMA = "{schema.upper()}"'
                    )
                cursor.execute("SELECT privilege FROM session_privs")
                system_privileges = self._first_column(cursor.fetchall())
                cursor.execute(
                    "SELECT privilege FROM user_tab_privs_recd"
                )
                object_privileges = self._first_column(cursor.fetchall())
                cursor.execute("SELECT granted_role FROM user_role_privs")
                roles = self._first_column(cursor.fetchall())
                readonly_account = (
                    "CREATE SESSION" in system_privileges
                    and system_privileges.issubset(
                        _ORACLE_ALLOWED_SYSTEM_PRIVILEGES
                    )
                    and object_privileges.issubset(
                        _ORACLE_ALLOWED_OBJECT_PRIVILEGES
                    )
                    and roles.issubset(_ORACLE_ALLOWED_ROLES)
                )
                if (
                    not readonly_account
                    and not self._allow_privileged_account
                ):
                    raise ReadonlyAccountViolation(
                        "Oracle account has a privileged role "
                        "or non-readonly permissions"
                    )
                cursor.execute(
                    "SELECT parameter, value "
                    "FROM nls_database_parameters "
                    "WHERE parameter IN "
                    "('NLS_CHARACTERSET', 'NLS_NCHAR_CHARACTERSET')"
                )
                character_sets = {
                    str(row[0]).upper(): str(row[1]).upper()
                    for row in cursor.fetchall()
                }
                if character_sets != {
                    "NLS_CHARACTERSET": "AL32UTF8",
                    "NLS_NCHAR_CHARACTERSET": "AL16UTF16",
                }:
                    raise ReadonlyAccountViolation(
                        "Oracle database character sets are incompatible"
                    )
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT 1 FROM dual")
                cursor.fetchone()
            finally:
                cursor.close()
            connection.rollback()
            client_version = "19c"
            client_architecture = "verified"
            if self._client_ready is None:
                from app.modules.internal_api_platform.infrastructure.db.oracle_client import (
                    thick_init_result,
                )

                client = thick_init_result()
                client_version = client.client_version or client_version
                client_architecture = (
                    client.architecture or client_architecture
                )
            return {
                "connection": True,
                "readonly_account": readonly_account,
                "privileged_account_allowed": not readonly_account,
                "readonly_transaction": True,
                "server_version": "11.2.0.4",
                "character_sets": character_sets,
                "client_mode": "thick",
                "client_version": client_version,
                "client_architecture": client_architecture,
            }
        finally:
            connection.close()

    @staticmethod
    def _first_column(rows: list[Any]) -> set[str]:
        return {
            str(
                row[0]
                if isinstance(row, (tuple, list))
                else next(iter(row.values()))
            ).upper()
            for row in rows
        }


class RedisResourceProbe:
    def __init__(
        self,
        connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._connect_factory = connect_factory

    def verify(
        self,
        config: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        assert_external_io_allowed("resource_verify.redis")
        connect = self._connect_factory
        if connect is None:
            import redis

            connect = redis.Redis
        tls = dict(config.get("tls") or {})
        client = connect(
            host=config["host"],
            port=int(config["port"]),
            db=int(config["db"]),
            username=config.get("username") or None,
            password=config.get("password") or None,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
            ssl=bool(tls.get("enabled", False)),
            ssl_cert_reqs=(
                "required"
                if tls.get("verify_certificate", True)
                else None
            ),
            ssl_check_hostname=bool(
                tls.get("enabled", False)
                and tls.get("verify_certificate", True)
            ),
            decode_responses=True,
        )
        try:
            if client.ping() is not True:
                raise RuntimeError("Redis PING did not succeed")
            return {
                "connection": True,
                "ping": True,
                "standalone": True,
                "tls": bool(tls.get("enabled", False)),
                "certificate_verification": bool(
                    tls.get("enabled", False)
                    and tls.get("verify_certificate", True)
                ),
                "database": int(config["db"]),
            }
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                close()


class LokiResourceProbe:
    def __init__(
        self,
        urlopen_func: Callable[..., Any] = urlopen,
    ) -> None:
        self._urlopen_func = urlopen_func

    def verify(
        self,
        config: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        assert_external_io_allowed("resource_verify.loki")
        effective_timeout = min(
            timeout_seconds,
            int(config["timeout_seconds"]),
        )
        headers = {"accept": "application/json"}
        tenant = str(config.get("tenant") or "")
        if tenant:
            headers["X-Scope-OrgID"] = tenant
        auth_token = str(config.get("auth_token") or "")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        request = Request(
            f"{str(config['base_url']).rstrip('/')}/loki/api/v1/status/buildinfo",
            headers=headers,
            method="GET",
        )
        with self._urlopen_func(
            request,
            timeout=effective_timeout,
        ) as response:
            raw = response.read(4097)
        if len(raw) > 4096:
            raise RuntimeError("Loki probe response is too large")
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError("Loki build info is invalid")
        return {
            "connection": True,
            "build_info": True,
            "tenant_configured": bool(tenant),
            "authentication_configured": bool(auth_token),
            "timeout_seconds": int(config["timeout_seconds"]),
            "max_minutes": int(config["max_minutes"]),
            "max_lines": int(config["max_lines"]),
            "max_response_bytes": int(config["max_response_bytes"]),
        }


class GovernedResourceTechnicalVerifier:
    def __init__(
        self,
        *,
        resolve_secret: Callable[[str], str],
        provider_contracts: ProviderContractRegistry | None = None,
        probes: dict[str, DatabaseReadonlyProbe] | None = None,
        timeout_seconds: int = 10,
        allow_oracle_real_verification: bool = False,
        allow_privileged_database_accounts: bool = False,
    ) -> None:
        self._resolve_secret = resolve_secret
        self._provider_contracts = (
            provider_contracts or ProviderContractRegistry()
        )
        self._probes = probes or {
            "mysql": MysqlReadonlyAccountProbe(
                allow_privileged_account=allow_privileged_database_accounts,
            ),
            "sqlserver": SqlServerReadonlyAccountProbe(
                allow_privileged_account=allow_privileged_database_accounts,
            ),
            "oracle": Oracle11gReadonlyAccountProbe(
                allow_privileged_account=allow_privileged_database_accounts,
            ),
            "redis": RedisResourceProbe(),
            "loki": LokiResourceProbe(),
        }
        self._timeout_seconds = timeout_seconds
        self._allow_oracle_real_verification = (
            allow_oracle_real_verification
        )

    def verify(
        self,
        *,
        resource: dict[str, Any],
        draft: dict[str, Any],
    ) -> ResourceVerificationOutcome:
        provider_type = str(draft["provider_type"])
        contract = self._provider_contracts.require(provider_type)
        probe = self._probes.get(provider_type)
        if (
            provider_type == "oracle"
            and not self._allow_oracle_real_verification
        ):
            return ResourceVerificationOutcome(
                status="BLOCKED",
                provider_contract_version=contract.contract_version,
                checks={
                    "available": False,
                    "real_connection_verified": False,
                },
                safe_error_summary=(
                    "真实 Oracle 11.2.0.4 连接验收尚未完成，禁止发布"
                ),
            )
        if probe is None:
            return ResourceVerificationOutcome(
                status="BLOCKED",
                provider_contract_version=contract.contract_version,
                checks={"available": False},
                safe_error_summary="该数据库 Provider 的技术验证器尚未实现",
            )
        runtime: dict[str, Any] = {}
        try:
            document = self._provider_contracts.normalize(
                provider_type=provider_type,
                config=dict(draft["config"]),
                secret_refs=dict(draft["secret_refs"]),
            )
            runtime = self._provider_contracts.runtime_projection(
                document,
                resolve_secret=self._resolve_secret,
            )
            checks = probe.verify(
                runtime,
                timeout_seconds=self._timeout_seconds,
            )
            return ResourceVerificationOutcome(
                status="PASSED",
                provider_contract_version=contract.contract_version,
                checks=checks,
                safe_error_summary=(
                    "本地环境已允许高权限 "
                    f"{self._provider_label(provider_type)} 账号；"
                    "技术测试仅执行只读探针"
                    if checks.get("privileged_account_allowed") is True
                    else ""
                ),
            )
        except ModuleNotFoundError:
            return ResourceVerificationOutcome(
                status="BLOCKED",
                provider_contract_version=contract.contract_version,
                checks={"available": False},
                safe_error_summary="数据库客户端未安装，无法执行技术验证",
            )
        except ReadonlyAccountViolation:
            return ResourceVerificationOutcome(
                status="FAILED",
                provider_contract_version=contract.contract_version,
                checks={
                    "connection": True,
                    "readonly_account": False,
                },
                safe_error_summary="数据库账号未通过只读权限检查",
            )
        except (json.JSONDecodeError, urllib.error.HTTPError):
            return ResourceVerificationOutcome(
                status="FAILED",
                provider_contract_version=contract.contract_version,
                checks={"connection": False},
                safe_error_summary="资源连接或技术探针执行失败",
            )
        except Exception:
            return ResourceVerificationOutcome(
                status="FAILED",
                provider_contract_version=contract.contract_version,
                checks={"connection": False},
                safe_error_summary="资源连接或技术探针执行失败",
            )
        finally:
            runtime.pop("password", None)
            runtime.pop("auth_token", None)

    @staticmethod
    def _provider_label(provider_type: str) -> str:
        return {
            "mysql": "MySQL",
            "sqlserver": "SQL Server",
            "oracle": "Oracle",
        }.get(provider_type, provider_type)


DatabaseResourceTechnicalVerifier = GovernedResourceTechnicalVerifier
