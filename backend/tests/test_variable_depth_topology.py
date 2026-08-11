from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.modules.authorization_center.infrastructure.repository import (
    AuthorizationCenterRepository,
)
from app.modules.platform_config.application.validation import (
    PlatformConfigValidationError,
)
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NotFound


@pytest.fixture
def topology_repository() -> PlatformConfigRepository:
    temporary = tempfile.TemporaryDirectory()
    database = Database(f"sqlite:///{Path(temporary.name) / 'topology.db'}")
    database.run_migrations(default_migrations_dir())
    repository = PlatformConfigRepository(database)
    try:
        yield repository
    finally:
        database.close()
        temporary.cleanup()


def test_topology_supports_environment_base_and_workshop_leaves_without_virtual_nodes(
    topology_repository: PlatformConfigRepository,
) -> None:
    topology_repository.upsert_environment(
        code="environment_leaf",
        display_name="Environment leaf",
    )
    topology_repository.upsert_environment(
        code="base_tree",
        display_name="Base tree",
    )
    topology_repository.upsert_base(
        environment_code="base_tree",
        code="base_leaf",
        engine="mysql",
    )
    topology_repository.upsert_environment(
        code="workshop_tree",
        display_name="Workshop tree",
    )
    topology_repository.upsert_base(
        environment_code="workshop_tree",
        code="workshop_parent",
        engine="oracle",
    )
    topology_repository.upsert_workshop(
        environment_code="workshop_tree",
        base_code="workshop_parent",
        code="GL001",
    )

    public = AuthorizationCenterRepository(topology_repository.database).topology_catalog()
    environments = {item["code"]: item for item in public}

    assert environments["environment_leaf"]["bases"] == []

    base_tree = environments["base_tree"]
    assert len(base_tree["bases"]) == 1
    base_leaf = base_tree["bases"][0]
    assert base_leaf["code"] == "base_leaf"
    assert base_leaf["workshops"] == []

    workshop_tree = environments["workshop_tree"]
    workshop_parent = workshop_tree["bases"][0]
    assert [item["code"] for item in workshop_parent["workshops"]] == ["GL001"]

    encoded = str(public).lower()
    assert "'code': 'default'" not in encoded
    assert "'code': 'none'" not in encoded


@pytest.mark.parametrize(
    "placeholder",
    [
        "default",
        "DEFAULT",
        "none",
        "null",
        "undefined",
        "not_applicable",
        "standalone",
        "cloud",
        "edge",
    ],
)
def test_topology_rejects_placeholder_nodes(
    topology_repository: PlatformConfigRepository,
    placeholder: str,
) -> None:
    topology_repository.upsert_environment(code="real_environment")
    topology_repository.upsert_base(
        environment_code="real_environment",
        code="real_base",
        engine="mysql",
    )

    with pytest.raises(PlatformConfigValidationError):
        topology_repository.upsert_environment(code=placeholder)
    with pytest.raises(PlatformConfigValidationError):
        topology_repository.upsert_base(
            environment_code="real_environment",
            code=placeholder,
            engine="mysql",
        )
    with pytest.raises(PlatformConfigValidationError):
        topology_repository.upsert_workshop(
            environment_code="real_environment",
            base_code="real_base",
            code=placeholder,
        )


def test_topology_rejects_children_without_their_exact_parent(
    topology_repository: PlatformConfigRepository,
) -> None:
    topology_repository.upsert_environment(code="environment_a")
    topology_repository.upsert_environment(code="environment_b")
    topology_repository.upsert_base(
        environment_code="environment_a",
        code="base_a",
        engine="mysql",
    )

    with pytest.raises(NotFound):
        topology_repository.upsert_base(
            environment_code="missing_environment",
            code="orphan_base",
            engine="mysql",
        )
    with pytest.raises(NotFound):
        topology_repository.upsert_workshop(
            environment_code="environment_b",
            base_code="base_a",
            code="orphan_workshop",
        )

    timestamp = "2026-08-06T00:00:00+00:00"
    with pytest.raises(Exception):
        topology_repository.database.execute(
            """
            insert into platform_base
              (id, environment_id, code, display_name, engine, status,
               created_at, updated_at)
            values ('orphan-base-row', 'missing-environment-row',
                    'orphan_base_row', '', 'mysql', 'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
    with pytest.raises(Exception):
        topology_repository.database.execute(
            """
            insert into platform_workshop
              (id, base_id, code, display_name, status, created_at, updated_at)
            values ('orphan-workshop-row', 'missing-base-row',
                    'orphan_workshop_row', '', 'enabled', ?, ?)
            """,
            (timestamp, timestamp),
        )
