from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import uuid

import pytest

from app.modules.api_capability.domain.contracts import content_hash
from app.modules.api_capability.infrastructure import ApiCapabilityRepository
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator
from backend.tests.test_governed_api_capability_repositories import (
    ACTOR_ID,
    _bound_identity,
    _published_capability,
    _published_connection,
)


POSTGRES_DSN = os.getenv("MIGRATION_POSTGRES_DSN", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_DSN,
    reason="set MIGRATION_POSTGRES_DSN to run governed API PostgreSQL integration",
)


@pytest.fixture
def postgres_database_dsn() -> str:
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    database_name = f"governed_api_test_{uuid.uuid4().hex}"
    with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(database_name)))
    parameters = conninfo_to_dict(POSTGRES_DSN)
    parameters["dbname"] = database_name
    test_dsn = make_conninfo(**parameters)
    try:
        yield test_dsn
    finally:
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
            admin.execute(
                """
                select pg_terminate_backend(pid)
                  from pg_stat_activity
                 where datname = %s and pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            admin.execute(sql.SQL("drop database {}").format(sql.Identifier(database_name)))


def test_postgres_concurrent_publish_is_idempotent_and_draft_save_is_unique(
    postgres_database_dsn: str,
) -> None:
    database = Database(postgres_database_dsn)
    try:
        result = Migrator(
            database,
            default_migrations_dir(),
            migrator_build="governed-api-postgres-test",
        ).run()
        assert result.head == "026"
        database.execute(
            """
            insert into app_user
              (id, username, display_name, status, created_at, updated_at)
            values (?, 'governed-api-admin', 'API Admin', 'enabled',
                    current_timestamp, current_timestamp)
            """,
            (ACTOR_ID,),
        )
        _, connection_revision = _published_connection(database)
        _, credential = _bound_identity(
            database,
            str(connection_revision["id"]),
        )
        repository, release = _published_capability(
            database,
            connection_revision,
            str(credential["external_identity_id"]),
        )
        capability = repository.get(str(release["capability_id"]))
        draft = capability["draft"]
        saved = repository.save_draft(
            str(capability["id"]),
            expected_revision=int(draft["draft_revision"]),
            connection_revision_id=str(draft["connection_revision_id"]),
            authentication_profile_revision_id=str(draft["authentication_profile_revision_id"]),
            capability=draft["capability"],
            handler={
                **draft["handler"],
                "relative_path": "/project/api/project/graphql/v2",
            },
            mapping_ast=draft["mapping_ast"],
            actor_id=ACTOR_ID,
        )
        changed = saved["draft"]
        repository.record_verification(
            str(capability["id"]),
            draft_revision=int(changed["draft_revision"]),
            draft_hash=str(changed["content_hash"]),
            external_identity_id=str(credential["external_identity_id"]),
            external_user_id="ones-user-admin",
            default_team_id="team-b",
            actor_id=ACTOR_ID,
            status="PASSED",
            result_summary={},
        )
        plan = {
            "schema_version": 1,
            "ast_hash": content_hash(changed["mapping_ast"]),
            "request_plan": {},
            "response_plan": {},
        }

        def publish() -> str:
            concurrent_database = Database(postgres_database_dsn)
            try:
                concurrent_repository = ApiCapabilityRepository(concurrent_database)
                published = concurrent_repository.create_release(
                    str(capability["id"]),
                    draft_revision=int(changed["draft_revision"]),
                    draft_hash=str(changed["content_hash"]),
                    idempotency_key="postgres-concurrent-release",
                    compiled_plan=plan,
                    compiled_plan_hash=content_hash(plan),
                    actor_id=ACTOR_ID,
                )
                return str(published["id"])
            finally:
                concurrent_database.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            published_ids = list(executor.map(lambda _: publish(), range(2)))
        assert len(set(published_ids)) == 1

        expected_revision = int(repository.get(str(capability["id"]))["draft"]["draft_revision"])

        def save(suffix: str) -> str:
            concurrent_database = Database(postgres_database_dsn)
            try:
                concurrent_repository = ApiCapabilityRepository(concurrent_database)
                concurrent_repository.save_draft(
                    str(capability["id"]),
                    expected_revision=expected_revision,
                    connection_revision_id=str(changed["connection_revision_id"]),
                    authentication_profile_revision_id=str(
                        changed["authentication_profile_revision_id"]
                    ),
                    capability=changed["capability"],
                    handler={
                        **changed["handler"],
                        "relative_path": (f"/project/api/project/graphql/{suffix}"),
                    },
                    mapping_ast=changed["mapping_ast"],
                    actor_id=ACTOR_ID,
                )
                return "saved"
            except NonRetryableExecutionError as exc:
                return exc.error_code
            finally:
                concurrent_database.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save, ("a", "b")))
        assert sorted(results) == ["revision_conflict", "saved"]
    finally:
        database.close()
