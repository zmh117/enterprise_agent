from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import bootstrap_admin as bootstrap_cli
from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application import AuthService
from app.modules.identity.application.passwords import PasswordService
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.infrastructure.repositories import AuditRepository
from app.shared.config import IdentitySettings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator


def _service(database: Database) -> tuple[AuthService, IdentityRepository]:
    repository = IdentityRepository(database)
    return (
        AuthService(
            repository,
            AuditService(AuditRepository(database), max_chars=4000),
            IdentitySettings(),
        ),
        repository,
    )


def test_local_default_bootstrap_creates_login_ready_argon2_admin() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="admin-test").run()
    service, repository = _service(database)

    user = service.bootstrap_admin(
        username="admin",
        display_name="Administrator",
        password=bootstrap_cli.LOCAL_DEFAULT_PASSWORD,
    )

    assert user is not None
    assert user["username"] == "admin"
    assert user["display_name"] == "Administrator"
    assert repository.admin_count() == 1
    password_hash = repository.get_password_hash(str(user["id"]))
    assert password_hash.startswith("$argon2")
    assert bootstrap_cli.LOCAL_DEFAULT_PASSWORD not in password_hash
    principal, _, _ = service.login(
        username="admin",
        password=bootstrap_cli.LOCAL_DEFAULT_PASSWORD,
    )
    assert "platform-admin" in principal.role_codes
    database.close()


def test_repeated_bootstrap_preserves_existing_admin_password_and_revision() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="admin-test").run()
    service, repository = _service(database)
    created = service.bootstrap_admin(
        username="admin",
        display_name="Administrator",
        password=bootstrap_cli.LOCAL_DEFAULT_PASSWORD,
    )
    assert created is not None
    user_id = str(created["id"])
    before_user = repository.get_user(user_id)
    before_hash = repository.get_password_hash(user_id)

    repeated = service.bootstrap_admin(
        username="different-admin",
        display_name="Must Not Replace",
        password="222222222222",
    )

    assert repeated is None
    assert repository.admin_count() == 1
    assert repository.get_user(user_id) == before_user
    assert repository.get_password_hash(user_id) == before_hash
    assert repository.get_user_by_username("different-admin") is None
    database.close()


def test_password_resolution_uses_local_default_and_rejects_nonlocal_missing_file(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-password"

    assert (
        bootstrap_cli.resolve_initial_admin_password(
            environment="test",
            password_file=missing,
            non_interactive=True,
        )
        == bootstrap_cli.LOCAL_DEFAULT_PASSWORD
    )
    with pytest.raises(
        bootstrap_cli.InitialAdminBootstrapError,
        match="requires a protected password file",
    ):
        bootstrap_cli.resolve_initial_admin_password(
            environment="production",
            password_file=missing,
            non_interactive=True,
        )


def test_nonlocal_password_file_must_be_regular_and_permission_restricted(
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "initial-admin-password"
    password_file.write_text("production-password-123\n", encoding="utf-8")
    password_file.chmod(0o600)

    assert (
        bootstrap_cli.resolve_initial_admin_password(
            environment="production",
            password_file=password_file,
            non_interactive=True,
        )
        == "production-password-123"
    )

    password_file.chmod(0o644)
    with pytest.raises(
        bootstrap_cli.InitialAdminBootstrapError,
        match="permissions",
    ):
        bootstrap_cli.resolve_initial_admin_password(
            environment="production",
            password_file=password_file,
            non_interactive=True,
        )


def test_cli_bootstrap_is_idempotent_and_never_prints_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "bootstrap.db"
    database_dsn = f"sqlite:///{database_path}"
    database = Database(database_dsn)
    try:
        Migrator(database, default_migrations_dir(), migrator_build="admin-cli-test").run()
    finally:
        database.close()
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_DSN", database_dsn)

    assert bootstrap_cli.main(["--non-interactive"]) == 0
    first_output = capsys.readouterr().out
    assert "status=created username=admin" in first_output
    assert bootstrap_cli.LOCAL_DEFAULT_PASSWORD not in first_output

    assert bootstrap_cli.main(["--non-interactive"]) == 0
    second_output = capsys.readouterr().out
    assert "status=existing_admin_preserved" in second_output
    assert bootstrap_cli.LOCAL_DEFAULT_PASSWORD not in second_output

    # Once an administrator exists, a production restart is a true no-op and
    # must not require the one-time bootstrap password file to remain mounted.
    monkeypatch.setenv("APP_ENV", "production")
    assert (
        bootstrap_cli.main(
            ["--non-interactive", "--password-file", str(tmp_path / "missing-password")]
        )
        == 0
    )
    production_output = capsys.readouterr().out
    assert "status=existing_admin_preserved" in production_output
    assert bootstrap_cli.LOCAL_DEFAULT_PASSWORD not in production_output

    verification = Database(database_dsn)
    try:
        repository = IdentityRepository(verification)
        user = repository.get_user_by_username("admin")
        assert user is not None
        assert PasswordService().verify(
            repository.get_password_hash(str(user["id"])),
            bootstrap_cli.LOCAL_DEFAULT_PASSWORD,
        )
    finally:
        verification.close()
