from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.apply_agent_runtime_grants import (
    PASSWORD_ENV,
    apply_agent_runtime_grants,
)
from app.shared.database import Database


def test_non_postgres_runtime_does_not_attempt_role_mutation(tmp_path: Path) -> None:
    database = Database("sqlite:///:memory:")
    try:
        status = apply_agent_runtime_grants(
            database,
            grants_path=tmp_path / "not-used.sql",
        )
    finally:
        database.close()
    assert status == "skipped_non_postgres"


def test_short_runtime_database_password_fails_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = Database("sqlite:///:memory:")
    database.engine = "postgres"  # type: ignore[assignment]
    monkeypatch.setenv(PASSWORD_ENV, "too-short")
    try:
        with pytest.raises(RuntimeError, match=PASSWORD_ENV):
            apply_agent_runtime_grants(database, grants_path=tmp_path / "unused.sql")
    finally:
        database.close()
