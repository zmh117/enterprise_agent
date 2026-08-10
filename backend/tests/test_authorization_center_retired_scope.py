from __future__ import annotations

import pytest

from app.modules.admin.application.scope import strict_business_scope_summary
from app.modules.authorization_center.infrastructure.repository import (
    AuthorizationCenterRepository,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


NOW = "2026-08-10T00:00:00+00:00"


@pytest.fixture
def database() -> Database:
    value = Database("sqlite:///:memory:")
    Migrator(value, default_migrations_dir(), migrator_build="retired-scope-test").run()
    value.execute(
        """
        insert into app_user
          (id, username, display_name, email, status, account_type,
           revision, created_at, updated_at)
        values ('user-1', 'admin', 'Admin', '', 'enabled', 'human', 1, ?, ?)
        """,
        (NOW, NOW),
    )
    value.execute(
        """
        insert into business_application
          (id, code, name, description, project_code, owner_user_id, status,
           revision, created_by, created_at, updated_at)
        values ('application-1', 'application-one', 'Application One', '', 'default',
                'user-1', 'enabled', 1, 'user-1', ?, ?)
        """,
        (NOW, NOW),
    )
    try:
        yield value
    finally:
        value.close()


def test_business_access_uses_only_application_identity_after_legacy_scope_retirement(
    database: Database,
) -> None:
    repository = AuthorizationCenterRepository(database)
    role = repository.create_role(
        code="application-user",
        name="Application User",
        description="",
        purpose_tags=[],
    )

    result = repository.replace_business_access(
        str(role["id"]),
        expected_revision=int(role["business_revision"]),
        applications=[{"application_id": "application-1"}],
    )

    assert result["applications"][0]["application_code"] == "application-one"
    assert "capability_codes" not in result["applications"][0]
    assert "scopes" not in result["applications"][0]

    with pytest.raises(NonRetryableExecutionError) as retired:
        repository.replace_business_access(
            str(role["id"]),
            expected_revision=int(result["revision"]),
            applications=[
                {
                    "application_id": "application-1",
                    "capability_codes": [],
                    "scopes": [],
                }
            ],
        )
    assert retired.value.error_code == "legacy_application_authorization_retired"


def test_retired_scope_summary_is_fail_closed_without_retired_tables(
    database: Database,
) -> None:
    assert strict_business_scope_summary(
        database, user_id="user-1", global_access=False
    ) == {"mode": "restricted", "grants": []}
    assert strict_business_scope_summary(
        database, user_id="user-1", global_access=True
    ) == {"mode": "global", "grants": []}
