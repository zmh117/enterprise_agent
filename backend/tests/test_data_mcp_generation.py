from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from services.data_mcp_server import generation as generation_module
from services.data_mcp_server.generation import DataGenerationReconciler


class _Provider:
    async def health_check(self) -> None:
        return None


class _Resolver:
    def load_building_generation(self, generation_id: str) -> object:
        assert generation_id == "generation-2"
        return object()


class _ActivationQuery:
    def __init__(self) -> None:
        self.events: list[str] = []

    def execute_one(self, sql: str, params=()):
        if "for update of g, d" in sql:
            self.events.append("lock")
            return {
                "id": "generation-2",
                "deployment_id": "deployment-1",
                "resource_revision_id": "revision-1",
            }
        if "update mcp_resource_generation" in sql:
            self.events.append("activate")
            return {
                "id": "generation-2",
                "deployment_id": "deployment-1",
                "resource_revision_id": "revision-1",
            }
        if "update mcp_resource_deployment" in sql:
            self.events.append("switch")
            return {"id": "deployment-1"}
        raise AssertionError(sql)

    def execute(self, sql: str, params=()):
        assert "status = 'SUPERSEDED'" in sql
        self.events.append("supersede")
        return []

    @contextmanager
    def unit_of_work(self):
        self.events.append("begin")
        yield
        self.events.append("commit")


def test_generation_activation_switches_old_and_new_status_in_one_transaction(
    monkeypatch,
) -> None:
    query = _ActivationQuery()
    reconciler = DataGenerationReconciler(
        SimpleNamespace(query=query),
        _Resolver(),
        builder_id="builder-1",
    )
    monkeypatch.setattr(generation_module, "build_provider", lambda resource: _Provider())

    assert reconciler._build_generation("generation-2") is True
    assert query.events == ["begin", "lock", "supersede", "activate", "switch", "commit"]


class _FailingActivationQuery:
    def __init__(self) -> None:
        self.failure_params: tuple[object, ...] = ()
        self.activation_attempted = False

    def execute_one(self, sql: str, params=()):
        if "for update of g, d" in sql:
            return {
                "id": "generation-2",
                "deployment_id": "deployment-1",
                "resource_revision_id": "revision-1",
            }
        self.activation_attempted = True
        raise RuntimeError("database details must not escape")

    def execute(self, sql: str, params=()):
        if "status = 'SUPERSEDED'" in sql:
            return []
        assert "generation_activation_failed" in sql
        self.failure_params = tuple(params)
        return []

    @contextmanager
    def unit_of_work(self):
        yield


def test_generation_activation_failure_is_persisted_with_safe_error(
    monkeypatch,
) -> None:
    query = _FailingActivationQuery()
    reconciler = DataGenerationReconciler(
        SimpleNamespace(query=query),
        _Resolver(),
        builder_id="builder-1",
    )
    monkeypatch.setattr(generation_module, "build_provider", lambda resource: _Provider())

    assert reconciler._build_generation("generation-2") is False
    assert query.activation_attempted is True
    assert query.failure_params == ("generation-2", "builder-1")


class _LatestStatusQuery:
    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params=()):
        assert not params
        self.sql = sql
        return [{"status": "ACTIVE", "count": 2}]


def test_generation_status_counts_only_latest_exact_deployment_generations() -> None:
    query = _LatestStatusQuery()
    reconciler = DataGenerationReconciler(SimpleNamespace(query=query), _Resolver())

    assert reconciler.status() == {
        "status": "ready",
        "active": 2,
        "building": 0,
        "failed": 0,
    }
    assert "candidate.resource_revision_id = d.resource_revision_id" in query.sql
    assert "max(candidate.generation)" in query.sql
