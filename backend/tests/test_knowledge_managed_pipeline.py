"""默认关闭的小时调度与阶段恢复；使用合成仓储和 SQLite，不接真实 ONES。"""

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from app.modules.knowledge.application.managed_sync_pipeline import ManagedSyncPipeline
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.cli.sync_ones_knowledge import execute_pipeline
from backend.tests.test_knowledge_import import database as database_fixture


database = database_fixture


class FakeStore:
    def __init__(self, phase: str | None, changed: set[str]) -> None:
        self.phase, self.changed = phase, changed
        self.error_code = None
        self.config = {
            "id": "binding",
            "enabled": 1,
            "resource_pins_json": {},
            "configuration_json": {
                "base_codes": {
                    "defect": "fake-defects",
                    "ticket": "fake-tickets",
                    "requirement": "fake-stories",
                }
            },
        }

    def binding(self, binding_id):
        return self.config

    def active_collection(self, binding_id):
        return {"id": "run", "phase": self.phase} if self.phase else None

    def run(self, run_id, *, lock=False):
        return {"id": run_id, "phase": self.phase, "binding_id": "binding"}

    def assert_configuration(self, run, *, lock=False):
        if self.config["enabled"] != 1:
            raise ExportValidationError("knowledge_collection_disabled")
        return self.config

    def changed_bases(self, run_id):
        return self.changed

    def advance(self, run_id, *, expected_phase, phase):
        assert self.phase == expected_phase
        self.phase = phase

    def fail(self, run_id, code):
        self.error_code = code

    def summary(self, run_id):
        return {"run_id": run_id, "phase": self.phase}


def test_pipeline_runs_each_stage_once_and_skips_unchanged_bases():
    defect = stable_id("base", "fake-defects")
    store = FakeStore(None, {defect})
    calls = []

    def collect(binding_id):
        calls.append("collect")
        store.phase = "STAGED"
        return {"run_id": "run"}

    def activate(run_id):
        calls.append("activate")
        store.phase = "ACTIVATED"
        return store.summary(run_id)

    pipeline = ManagedSyncPipeline(
        store,
        collect_once=collect,
        chunk_base=lambda run_id, code, profile: calls.append(("chunk", code, profile.version)),
        index_base=lambda run_id, code, profile: calls.append(("index", code, profile.version)),
        activate=activate,
    )
    assert pipeline.run_once("binding")["phase"] == "ACTIVATED"
    assert calls == [
        "collect",
        ("chunk", "fake-defects", "ones-work-item-chunks/v1"),
        ("index", "fake-defects", "ones-work-item-chunks/v1"),
        "activate",
    ]


@pytest.mark.parametrize("phase", ["CHUNKING", "INDEXING", "VERIFIED"])
def test_pipeline_resumes_persisted_phase_without_new_collection(phase):
    store = FakeStore(phase, {stable_id("base", "fake-defects")})
    calls = []
    pipeline = ManagedSyncPipeline(
        store,
        collect_once=lambda _: pytest.fail("must resume same run"),
        chunk_base=lambda *_: calls.append("chunk"),
        index_base=lambda *_: calls.append("index"),
        activate=lambda _: {"run_id": "run", "phase": "ACTIVATED"},
    )
    assert pipeline.run_once("binding")["phase"] == "ACTIVATED"
    assert calls == (
        ["chunk", "index"] if phase == "CHUNKING" else ["index"] if phase == "INDEXING" else []
    )


def test_pipeline_no_change_run_does_not_chunk_or_index():
    store = FakeStore("STAGED", set())
    pipeline = ManagedSyncPipeline(
        store,
        collect_once=lambda _: pytest.fail("already staged"),
        chunk_base=lambda *_: pytest.fail("no changed KB"),
        index_base=lambda *_: pytest.fail("no changed KB"),
        activate=lambda _: {"run_id": "run", "phase": "ACTIVATED"},
    )
    assert pipeline.run_once("binding")["phase"] == "ACTIVATED"


def test_pipeline_stops_after_disable_and_keeps_safe_failure_code():
    store = FakeStore("CHUNKING", {stable_id("base", "fake-defects")})

    def disable(*_):
        store.config["enabled"] = 0
        raise ExportValidationError("knowledge_collection_disabled")

    pipeline = ManagedSyncPipeline(
        store,
        collect_once=lambda _: pytest.fail("already staged"),
        chunk_base=disable,
        index_base=lambda *_: pytest.fail("must not index"),
        activate=lambda _: pytest.fail("must not activate"),
    )
    with pytest.raises(ExportValidationError, match="knowledge_collection_disabled"):
        pipeline.run_once("binding")
    assert store.phase == "CHUNKING" and store.error_code == "knowledge_collection_disabled"


def test_hourly_due_coalesces_long_run_and_resets_after_explicit_disable(database):
    repo = SyncRepository(database)
    config = {
        "base_codes": {
            "defect": "sched-defects",
            "ticket": "sched-tickets",
            "requirement": "sched-stories",
        },
        "resource_ids": [],
        "collector": {
            "provider_origin": "https://ones.example.test",
            "team_id": "synthetic-team",
            "project_ids": ["synthetic-project"],
            "issue_types": {
                "defect": ["synthetic-defect"],
                "ticket": ["synthetic-ticket"],
                "requirement": ["synthetic-story"],
            },
            "child_type_ids": ["synthetic-child"],
            "first_date": "2024-01-01",
            "credential_ref": "secret://platform/synthetic-collector",
        },
    }
    binding = repo.configure(
        code="synthetic-schedule",
        source_code="synthetic-schedule-source",
        configuration=config,
        expected_revision=0,
    )
    assert not repo.scheduled_due(binding["id"], datetime.now().astimezone())
    binding = repo.set_collection_enabled(binding["id"], enabled=True, expected_revision=1)
    due = binding["next_run_at"]
    if isinstance(due, str):
        due = datetime.fromisoformat(due)
    assert not repo.scheduled_due(binding["id"], due - timedelta(microseconds=1))
    assert repo.scheduled_due(binding["id"], due)
    run = repo.begin_collection(binding["id"], due.isoformat())
    repo.scheduled_started(binding["id"], run["id"], due)
    assert repo.scheduled_due(binding["id"], due - timedelta(microseconds=1))
    assert repo.scheduled_due(binding["id"], due + timedelta(hours=5))
    assert repo.active_run(binding["id"])["id"] == run["id"]
    repo.cancel(run["id"])
    assert repo.scheduled_due(binding["id"], due + timedelta(hours=5))
    repo.set_collection_enabled(binding["id"], enabled=False, expected_revision=1)
    assert not repo.scheduled_due(binding["id"], due + timedelta(hours=5))
    assert repo.binding(binding["id"])["next_run_at"] is None


def test_pipeline_lock_rechecks_due_before_second_writer_starts():
    class ScheduledRepository:
        locked = False

        @contextmanager
        def source_lock(self, source_id):
            assert source_id == stable_id("sync-worker", "binding")
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

        def scheduled_due(self, binding_id, at):
            assert binding_id == "binding" and self.locked
            return False

    repo = ScheduledRepository()

    class Pipeline:
        def run_once(self, binding_id):
            pytest.fail("the preceding writer already consumed this tick")

    assert execute_pipeline(repo, "binding", Pipeline(), scheduled=True) is None
    assert not repo.locked


def test_pipeline_lock_covers_entire_explicit_run():
    class ScheduledRepository:
        locked = False

        @contextmanager
        def source_lock(self, source_id):
            assert source_id == stable_id("sync-worker", "binding")
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

    repo = ScheduledRepository()

    class Pipeline:
        def run_once(self, binding_id):
            assert binding_id == "binding" and repo.locked
            return {"phase": "ACTIVATED"}

    assert execute_pipeline(repo, "binding", Pipeline(), scheduled=False) == {"phase": "ACTIVATED"}
    assert not repo.locked
