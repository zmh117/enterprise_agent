from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.platform_config.application.database_resource_verifier import (
    DatabaseResourceTechnicalVerifier,
    LokiResourceProbe,
    MysqlReadonlyAccountProbe,
    Oracle11gReadonlyAccountProbe,
    ReadonlyAccountViolation,
    RedisResourceProbe,
    SqlServerReadonlyAccountProbe,
)


class FakeCursor:
    def __init__(self, responses: dict[str, list[tuple[Any, ...]]]) -> None:
        self.responses = responses
        self.executed: list[str] = []
        self.current: list[tuple[Any, ...]] = []
        self.closed = False

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self.close()

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        self.current = list(self.responses.get(sql, []))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.current)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.current[0] if self.current else None

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False
        self.rolled_back = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class FakeOracleConnection(FakeConnection):
    version = "11.2.0.4.0"
    call_timeout = 0


class FakeOracleDriver:
    def __init__(self, connection: FakeOracleConnection) -> None:
        self.connection = connection
        self.dsn_kwargs: dict[str, Any] = {}
        self.connect_kwargs: dict[str, Any] = {}

    @staticmethod
    def is_thin_mode() -> bool:
        return False

    def makedsn(
        self,
        host: str,
        port: int,
        **kwargs: Any,
    ) -> str:
        self.dsn_kwargs = {
            "host": host,
            "port": port,
            **kwargs,
        }
        return "structured-oracle-dsn"

    def connect(self, **kwargs: Any) -> FakeOracleConnection:
        self.connect_kwargs = kwargs
        return self.connection


def _runtime_config(password: str = "canary-database-password") -> dict[str, Any]:
    return {
        "host": "db.internal",
        "port": 3306,
        "database": "orders",
        "user": "reader",
        "password": password,
    }


def test_mysql_probe_accepts_only_readonly_grants_and_sets_guards() -> None:
    cursor = FakeCursor(
        {
            "SHOW GRANTS FOR CURRENT_USER": [
                ("GRANT USAGE ON *.* TO `reader`@`%`",),
                ("GRANT SELECT, SHOW VIEW ON `orders`.* TO `reader`@`%`",),
            ],
            "SELECT 1": [(1,)],
        }
    )
    connection = FakeConnection(cursor)
    connect_kwargs: dict[str, Any] = {}

    def connect(**kwargs: Any) -> FakeConnection:
        connect_kwargs.update(kwargs)
        return connection

    checks = MysqlReadonlyAccountProbe(connect).verify(
        _runtime_config(),
        timeout_seconds=7,
    )

    assert checks == {
        "connection": True,
        "readonly_account": True,
        "privileged_account_allowed": False,
        "readonly_session": True,
        "grant_count": 2,
    }
    assert connect_kwargs["user"] == "reader"
    assert connect_kwargs["password"] == "canary-database-password"
    assert "SET SESSION TRANSACTION READ ONLY" in cursor.executed
    assert "SET SESSION MAX_EXECUTION_TIME = 7000" in cursor.executed
    assert "START TRANSACTION READ ONLY" in cursor.executed
    assert connection.rolled_back is True
    assert connection.closed is True


@pytest.mark.parametrize(
    "grant",
    [
        "GRANT SELECT, INSERT ON `orders`.* TO `reader`@`%`",
        "GRANT ALL PRIVILEGES ON `orders`.* TO `reader`@`%`",
        "GRANT SELECT ON `orders`.* TO `reader`@`%` WITH GRANT OPTION",
        "GRANT `readonly_role`@`%` TO `reader`@`%`",
    ],
)
def test_mysql_probe_fails_closed_for_non_readonly_grants(grant: str) -> None:
    cursor = FakeCursor({"SHOW GRANTS FOR CURRENT_USER": [(grant,)]})
    connection = FakeConnection(cursor)

    with pytest.raises(ReadonlyAccountViolation):
        MysqlReadonlyAccountProbe(lambda **_kwargs: connection).verify(
            _runtime_config(),
            timeout_seconds=5,
        )
    assert connection.closed is True


def test_mysql_probe_allows_privileged_account_only_when_explicit() -> None:
    cursor = FakeCursor(
        {
            "SHOW GRANTS FOR CURRENT_USER": [
                ("GRANT ALL PRIVILEGES ON *.* TO `root`@`%` WITH GRANT OPTION",),
            ],
            "SELECT 1": [(1,)],
        }
    )
    connection = FakeConnection(cursor)

    checks = MysqlReadonlyAccountProbe(
        lambda **_kwargs: connection,
        allow_privileged_account=True,
    ).verify(
        {
            **_runtime_config(),
            "user": "root",
        },
        timeout_seconds=5,
    )

    assert checks == {
        "connection": True,
        "readonly_account": False,
        "privileged_account_allowed": True,
        "readonly_session": True,
        "grant_count": 1,
    }
    assert "SET SESSION TRANSACTION READ ONLY" in cursor.executed
    assert "START TRANSACTION READ ONLY" in cursor.executed
    assert connection.rolled_back is True
    assert connection.closed is True


def test_sqlserver_probe_accepts_readonly_permissions_and_sets_timeout() -> None:
    cursor = FakeCursor({})

    def execute(sql: str) -> None:
        cursor.executed.append(sql)
        if sql.startswith("SELECT IS_SRVROLEMEMBER"):
            cursor.current = [(0,) * 14]
        elif "fn_my_permissions" in sql:
            cursor.current = [("CONNECT",), ("SELECT",), ("VIEW DEFINITION",)]
        elif sql == "SELECT 1":
            cursor.current = [(1,)]
        else:
            cursor.current = []

    cursor.execute = execute  # type: ignore[method-assign]
    connection = FakeConnection(cursor)
    config = {**_runtime_config(), "port": 1433}

    checks = SqlServerReadonlyAccountProbe(
        lambda **_kwargs: connection
    ).verify(config, timeout_seconds=4)

    assert checks["readonly_account"] is True
    assert "SET LOCK_TIMEOUT 4000" in cursor.executed
    assert cursor.closed is True
    assert connection.closed is True


@pytest.mark.parametrize(
    ("membership", "permissions"),
    [
        ((1,) + (0,) * 13, [("SELECT",)]),
        ((0,) * 14, [("SELECT",), ("UPDATE",)]),
        ((0,) * 14, [("CONTROL",)]),
    ],
)
def test_sqlserver_probe_rejects_roles_and_write_permissions(
    membership: tuple[int, ...],
    permissions: list[tuple[str]],
) -> None:
    cursor = FakeCursor({})

    def execute(sql: str) -> None:
        cursor.executed.append(sql)
        cursor.current = (
            [membership]
            if sql.startswith("SELECT IS_SRVROLEMEMBER")
            else permissions
        )

    cursor.execute = execute  # type: ignore[method-assign]
    connection = FakeConnection(cursor)

    with pytest.raises(ReadonlyAccountViolation):
        SqlServerReadonlyAccountProbe(
            lambda **_kwargs: connection
        ).verify(
            {**_runtime_config(), "port": 1433},
            timeout_seconds=5,
        )
    assert connection.closed is True


def test_database_verifier_resolves_secret_in_memory_without_persisting_it() -> None:
    password = "canary-database-password"

    class CapturingProbe:
        def verify(
            self,
            config: dict[str, Any],
            *,
            timeout_seconds: int,
        ) -> dict[str, Any]:
            assert config["password"] == password
            assert timeout_seconds == 9
            return {"connection": True, "readonly_account": True}

    verifier = DatabaseResourceTechnicalVerifier(
        resolve_secret=lambda ref: (
            password
            if ref == "secret://platform/mysql_password"
            else ""
        ),
        probes={"mysql": CapturingProbe()},
        timeout_seconds=9,
    )
    outcome = verifier.verify(
        resource={"resource_kind": "database"},
        draft={
            "provider_type": "mysql",
            "config": {
                "host": "mysql",
                "port": 3306,
                "database": "orders",
                "username": "reader",
            },
            "secret_refs": {
                "password_ref": "secret://platform/mysql_password"
            },
        },
    )

    assert outcome.status == "PASSED"
    assert outcome.provider_contract_version == "mysql_v1"
    assert password not in json.dumps(outcome.checks)


def test_database_verifier_returns_safe_failure_without_driver_error_details() -> None:
    password = "canary-database-password"

    class FailingProbe:
        def verify(
            self,
            config: dict[str, Any],
            *,
            timeout_seconds: int,
        ) -> dict[str, Any]:
            del config, timeout_seconds
            raise RuntimeError(
                f"server=db.internal password={password}"
            )

    verifier = DatabaseResourceTechnicalVerifier(
        resolve_secret=lambda _ref: password,
        probes={"mysql": FailingProbe()},
    )
    outcome = verifier.verify(
        resource={"resource_kind": "database"},
        draft={
            "provider_type": "mysql",
            "config": {
                "host": "mysql",
                "port": 3306,
                "database": "orders",
                "username": "reader",
            },
            "secret_refs": {
                "password_ref": "secret://platform/mysql_password"
            },
        },
    )

    serialized = json.dumps(
        {
            "checks": outcome.checks,
            "safe_error_summary": outcome.safe_error_summary,
        },
        ensure_ascii=False,
    )
    assert outcome.status == "FAILED"
    assert password not in serialized
    assert "db.internal" not in serialized


@pytest.mark.parametrize(
    ("address_key", "expected_dsn_key"),
    [("service_name", "service_name"), ("sid", "sid")],
)
def test_oracle_11g_probe_uses_structured_thick_readonly_contract(
    address_key: str,
    expected_dsn_key: str,
) -> None:
    cursor = FakeCursor({})

    def execute(sql: str) -> None:
        cursor.executed.append(sql)
        if sql == "SELECT privilege FROM session_privs":
            cursor.current = [
                ("CREATE SESSION",),
                ("SELECT ANY TABLE",),
            ]
        elif sql == "SELECT privilege FROM user_tab_privs_recd":
            cursor.current = [("SELECT",)]
        elif sql == "SELECT granted_role FROM user_role_privs":
            cursor.current = [("CONNECT",)]
        elif "FROM nls_database_parameters" in sql:
            cursor.current = [
                ("NLS_CHARACTERSET", "AL32UTF8"),
                ("NLS_NCHAR_CHARACTERSET", "AL16UTF16"),
            ]
        elif sql == "SELECT 1 FROM dual":
            cursor.current = [(1,)]
        else:
            cursor.current = []

    cursor.execute = execute  # type: ignore[method-assign]
    connection = FakeOracleConnection(cursor)
    driver = FakeOracleDriver(connection)
    probe = Oracle11gReadonlyAccountProbe(
        oracledb_module=driver,
        client_ready=lambda: None,
    )
    checks = probe.verify(
        {
            "host": "oracle.internal",
            "port": 1521,
            address_key: "ORCL",
            "user": "reader",
            "password": "oracle-canary-password",
            "schema": "APP_READ",
        },
        timeout_seconds=8,
    )

    assert driver.dsn_kwargs == {
        "host": "oracle.internal",
        "port": 1521,
        expected_dsn_key: "ORCL",
    }
    assert driver.connect_kwargs["dsn"] == "structured-oracle-dsn"
    assert connection.call_timeout == 8000
    assert "SET TRANSACTION READ ONLY" in cursor.executed
    assert checks["server_version"] == "11.2.0.4"
    assert checks["character_sets"] == {
        "NLS_CHARACTERSET": "AL32UTF8",
        "NLS_NCHAR_CHARACTERSET": "AL16UTF16",
    }
    assert connection.rolled_back is True
    assert connection.closed is True


def test_oracle_probe_rejects_write_system_privilege() -> None:
    cursor = FakeCursor({})

    def execute(sql: str) -> None:
        cursor.executed.append(sql)
        cursor.current = (
            [("CREATE SESSION",), ("UPDATE ANY TABLE",)]
            if sql == "SELECT privilege FROM session_privs"
            else []
        )

    cursor.execute = execute  # type: ignore[method-assign]
    connection = FakeOracleConnection(cursor)
    driver = FakeOracleDriver(connection)

    with pytest.raises(ReadonlyAccountViolation):
        Oracle11gReadonlyAccountProbe(
            oracledb_module=driver,
            client_ready=lambda: None,
        ).verify(
            {
                "host": "oracle.internal",
                "port": 1521,
                "service_name": "ORCL",
                "user": "reader",
                "password": "oracle-canary-password",
            },
            timeout_seconds=8,
        )
    assert connection.closed is True


def test_oracle_publication_verification_remains_blocked_without_real_gate() -> None:
    probe_called = False

    class ForbiddenFakeProbe:
        def verify(
            self,
            config: dict[str, Any],
            *,
            timeout_seconds: int,
        ) -> dict[str, Any]:
            del config, timeout_seconds
            nonlocal probe_called
            probe_called = True
            return {}

    outcome = DatabaseResourceTechnicalVerifier(
        resolve_secret=lambda _ref: "oracle-canary-password",
        probes={"oracle": ForbiddenFakeProbe()},
    ).verify(
        resource={"resource_kind": "database"},
        draft={
            "provider_type": "oracle",
            "config": {
                "host": "oracle.internal",
                "port": 1521,
                "service_name": "ORCL",
                "username": "reader",
            },
            "secret_refs": {
                "password_ref": "secret://platform/oracle_password"
            },
        },
    )

    assert outcome.status == "BLOCKED"
    assert outcome.checks["real_connection_verified"] is False
    assert probe_called is False


def test_redis_probe_uses_canonical_database_auth_and_tls() -> None:
    connect_kwargs: dict[str, Any] = {}

    class Client:
        closed = False

        @staticmethod
        def ping() -> bool:
            return True

        def close(self) -> None:
            self.closed = True

    client = Client()

    def connect(**kwargs: Any) -> Client:
        connect_kwargs.update(kwargs)
        return client

    checks = RedisResourceProbe(connect).verify(
        {
            "host": "redis.internal",
            "port": 6380,
            "db": 3,
            "username": "reader",
            "password": "redis-canary-password",
            "tls": {
                "enabled": True,
                "verify_certificate": True,
            },
        },
        timeout_seconds=6,
    )

    assert connect_kwargs["db"] == 3
    assert connect_kwargs["username"] == "reader"
    assert connect_kwargs["password"] == "redis-canary-password"
    assert connect_kwargs["ssl"] is True
    assert connect_kwargs["ssl_cert_reqs"] == "required"
    assert connect_kwargs["socket_connect_timeout"] == 6
    assert checks["tls"] is True
    assert "redis-canary-password" not in json.dumps(checks)
    assert client.closed is True


def test_loki_probe_uses_bound_tenant_auth_timeout_without_leaking_token() -> None:
    captured: dict[str, Any] = {}
    token = "loki-canary-bearer-token"

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def read(_size: int = -1) -> bytes:
            return b'{"version":"3.0.0"}'

    def fetch(request: Any, timeout: int) -> Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    checks = LokiResourceProbe(fetch).verify(
        {
            "base_url": "http://loki.internal:3100",
            "tenant": "tenant-a",
            "auth_token": token,
            "timeout_seconds": 7,
            "max_minutes": 30,
            "max_lines": 200,
            "max_response_bytes": 65536,
        },
        timeout_seconds=10,
    )

    request = captured["request"]
    headers = dict(request.header_items())
    assert captured["timeout"] == 7
    assert headers["X-scope-orgid"] == "tenant-a"
    assert headers["Authorization"] == f"Bearer {token}"
    assert checks["authentication_configured"] is True
    assert token not in json.dumps(checks)


@pytest.mark.parametrize("provider_type", ["redis", "loki"])
def test_non_database_provider_can_pass_governed_verification(
    provider_type: str,
) -> None:
    class PassingProbe:
        def verify(
            self,
            config: dict[str, Any],
            *,
            timeout_seconds: int,
        ) -> dict[str, Any]:
            assert timeout_seconds == 10
            assert "password_ref" not in config
            assert "auth_ref" not in config
            return {"connection": True}

    if provider_type == "redis":
        resource_kind = "redis"
        config = {
            "host": "redis",
            "port": 6379,
            "database": 0,
            "tls": {
                "enabled": False,
                "verify_certificate": True,
            },
        }
        refs = {
            "password_ref": "secret://platform/redis_password"
        }
    else:
        resource_kind = "loki"
        config = {
            "base_url": "http://loki:3100",
            "tenant_id": "tenant-a",
            "timeout_seconds": 5,
            "max_minutes": 60,
            "max_lines": 500,
            "max_response_bytes": 65536,
        }
        refs = {"auth_ref": "secret://platform/loki_auth"}
    outcome = DatabaseResourceTechnicalVerifier(
        resolve_secret=lambda _ref: "runtime-canary-secret",
        probes={provider_type: PassingProbe()},
    ).verify(
        resource={"resource_kind": resource_kind},
        draft={
            "provider_type": provider_type,
            "config": config,
            "secret_refs": refs,
        },
    )

    assert outcome.status == "PASSED"
