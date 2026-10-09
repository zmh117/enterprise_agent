"""知识 CLI 恢复合同；合成故障，不连接真实数据库/ONES。"""

from contextlib import contextmanager
import signal
from threading import Event
from types import SimpleNamespace

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from app.cli import collect_ones_knowledge, sync_ones_knowledge
from app.cli import knowledge_database_recovery as recovery
from app.modules.knowledge.application.ones_collection_service import KnowledgeOnesCollectionService
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.domain.chunking import KEEP_IDS_PROFILE
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.infrastructure.storage import source_lock
from app.modules.knowledge.infrastructure.content_access import ManagedContentAccess
from app.modules.knowledge.infrastructure.ones_collection_factory import (
    ManagedOnesCollectionProviderFactory,
)
from app.shared.migrations import SchemaHeadError
from backend.tests.test_knowledge_import import database as database_fixture
from backend.tests.test_knowledge_managed_pipeline import FakeStore, ManagedSyncPipeline
from backend.tests.test_knowledge_ones_collection import FIRST, Provider, _enabled_binding
from backend.tests.test_knowledge_sync_compose import _synthetic_file_key_settings
from backend.tests.test_knowledge_sync_compose import _stub_schema
from backend.tests.test_knowledge_vectors import prepared as vector_fixture


database = database_fixture
prepared = vector_fixture


@pytest.mark.parametrize(
    "error, expected",
    [
        (psycopg.errors.AdminShutdown("synthetic"), True),
        (psycopg.errors.CrashShutdown("synthetic"), True),
        (psycopg.errors.CannotConnectNow("synthetic"), True),
        (psycopg.errors.ConnectionFailure("synthetic"), True),
        (psycopg.OperationalError("connection refused"), True),
        (psycopg.OperationalError("server closed the connection unexpectedly"), True),
        (psycopg.InterfaceError("the connection is closed"), True),
        (psycopg.errors.InvalidPassword("synthetic"), False),
        (psycopg.errors.InsufficientPrivilege("synthetic"), False),
        (psycopg.errors.InvalidCatalogName("synthetic"), False),
        (psycopg.errors.UndefinedTable("synthetic"), False),
        (psycopg.errors.QueryCanceled("synthetic"), False),
        (psycopg.OperationalError("password authentication failed"), False),
        (psycopg.OperationalError("server does not support SSL"), False),
        (psycopg.OperationalError("unknown connection configuration"), False),
        (psycopg.OperationalError("connection refused; password authentication failed"), False),
        (ExportValidationError("knowledge_sync_configuration_changed"), False),
        (SchemaHeadError("synthetic mismatch"), False),
        (TimeoutError("ONES HTTP timeout"), False),
    ],
)
def test_only_known_database_disconnects_are_retried(error, expected):
    assert recovery.transient_database_error(error, "synthetic-unused") is expected


@pytest.mark.parametrize("connected", [False, True])
def test_docker_dns_absence_requires_previously_verified_database(connected):
    error = psycopg.OperationalError("could not translate host name: Name or service not known")
    assert (
        recovery.transient_database_error(error, "unused", previously_connected=connected)
        is connected
    )


@pytest.mark.parametrize(
    "error",
    [
        psycopg.errors.InvalidPassword("synthetic"),
        psycopg.errors.InsufficientPrivilege("synthetic"),
        SchemaHeadError("mismatch"),
        ExportValidationError("knowledge_sync_configuration_changed"),
    ],
)
def test_permanent_failures_do_not_wait_or_repeat_attempt(monkeypatch, error):
    stop = Event()
    monkeypatch.setattr(stop, "wait", lambda *_: pytest.fail("must not wait"))
    calls = []

    def attempt():
        calls.append(1)
        raise error

    with pytest.raises(type(error)) as caught:
        recovery.recover_database(
            attempt,
            dsn="unused",
            stop=stop,
            emit=lambda *_: pytest.fail("must not report retry"),
            prefix="knowledge_sync",
        )
    assert caught.value is error and calls == [1]


@pytest.mark.parametrize(
    "failure, expected",
    [
        (None, True),
        (psycopg.OperationalError("connection refused"), True),
        (psycopg.OperationalError("password authentication failed"), False),
        (psycopg.errors.InvalidCatalogName("synthetic"), False),
    ],
)
def test_pool_timeout_probes_without_retrying_permanent_auth_errors(monkeypatch, failure, expected):
    @contextmanager
    def probe(dsn, *, connect_timeout):
        assert (dsn, connect_timeout) == ("synthetic-unused", 5)
        if failure is not None:
            raise failure
        yield object()

    monkeypatch.setattr(recovery.psycopg, "connect", probe)
    assert recovery.transient_database_error(PoolTimeout(), "synthetic-unused") is expected


def test_retry_backoff_caps_at_sixty_and_does_not_leak_errors(monkeypatch):
    stop, delays, events = Event(), [], []
    monkeypatch.setattr(stop, "wait", lambda delay: delays.append(delay) or False)
    attempts = 0

    def attempt():
        nonlocal attempts
        attempts += 1
        if attempts <= 7:
            raise psycopg.errors.AdminShutdown("synthetic-private-dsn-and-body")
        return "completed"

    assert (
        recovery.recover_database(
            attempt,
            dsn="synthetic-unused",
            stop=stop,
            emit=lambda event, value: events.append((event, value)),
            prefix="knowledge_sync",
        )
        == "completed"
    )
    assert delays == [5, 10, 20, 40, 60, 60, 60]
    assert len(events) == 7 and "synthetic-private" not in str(events)


def test_stop_interrupts_database_wait_and_restores_signal_handlers(monkeypatch):
    stop = Event()
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    def wait(_delay):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return stop.is_set()

    monkeypatch.setattr(stop, "wait", wait)
    with (
        recovery.stop_signals(stop),
        pytest.raises(ExportValidationError, match="knowledge_sync_cancelled"),
    ):
        recovery.recover_database(
            lambda: (_ for _ in ()).throw(psycopg.errors.AdminShutdown()),
            dsn="synthetic-unused",
            stop=stop,
            emit=lambda *_: None,
            prefix="knowledge_sync",
        )
    assert all(signal.getsignal(sig) == handler for sig, handler in previous.items())


@pytest.mark.parametrize("mode", ["collect-once", "sync-once", "sync-daemon"])
def test_each_writing_cli_recovers_with_same_checkpoint(monkeypatch, tmp_path, capsys, mode):
    module = collect_ones_knowledge if mode == "collect-once" else sync_ones_knowledge
    settings, key = _synthetic_file_key_settings(tmp_path)
    monkeypatch.setattr(module, "load_settings", lambda: settings)
    monkeypatch.setenv("KNOWLEDGE_SYNC_ENABLED", "true")
    monkeypatch.setattr(Event, "wait", lambda *_: False)
    attempts = []

    def attempt(*args):
        checkpoint = args[-1]
        attempts.append(checkpoint)
        assert args[0 if mode == "collect-once" else 1].app_config_master_key == key
        if len(attempts) == 1:
            checkpoint.select_run("synthetic-run")
            raise psycopg.errors.AdminShutdown("synthetic-private-error")
        assert checkpoint.run_id == "synthetic-run"
        return {"run_id": checkpoint.run_id} if mode == "collect-once" else 0

    monkeypatch.setattr(module, "_collect_once" if mode == "collect-once" else "_execute", attempt)
    args = [
        "--mode",
        "daemon" if mode == "sync-daemon" else "once",
        "--binding-code",
        "synthetic",
        "--commit",
    ]
    if mode != "collect-once":
        args += ["--capacity-path", str(tmp_path)]
    assert module.main(args) == 0
    assert len(attempts) == 2 and attempts[0] is attempts[1]
    output = capsys.readouterr().out
    assert "database_retry_pending" in output
    assert key not in output and "synthetic-private-error" not in output


def test_checkpoint_rejects_changed_configuration_and_different_run():
    checkpoint = recovery.RecoveryCheckpoint()
    binding = {
        "id": "binding",
        "source_id": "source",
        "configuration_revision": 1,
        "configuration_hash": "hash",
    }
    checkpoint.check_binding(binding)
    checkpoint.check_binding(dict(binding))
    with pytest.raises(ExportValidationError, match="configuration_changed"):
        checkpoint.check_binding({**binding, "configuration_revision": 2})
    checkpoint.select_run("run")
    with pytest.raises(ExportValidationError, match="run_changed"):
        checkpoint.select_run("other-run")


def test_chunking_preserves_database_disconnect_cause():
    error = psycopg.errors.AdminShutdown("synthetic")
    repository = SimpleNamespace(
        profile=KEEP_IDS_PROFILE, scope=lambda _: (_ for _ in ()).throw(error)
    )
    with pytest.raises(ExportValidationError, match="knowledge_chunk_processing_failed") as caught:
        ChunkService(repository).run(knowledge_base_code="synthetic", expected_count=1, commit=True)
    assert recovery.database_error(caught.value) is error


def test_activation_content_connection_preserves_database_cause(database):
    error = psycopg.errors.AdminShutdown("synthetic")
    content = ManagedContentAccess(database, lambda *a: {})
    with (
        pytest.raises(KnowledgeGovernanceError, match="knowledge_storage_unavailable") as caught,
        content.open(None, knowledge_base_id="synthetic", revision_id="synthetic"),
    ):
        raise error
    assert recovery.database_error(caught.value) is error


def test_collection_preserves_disconnect_when_failure_marking_also_fails(database, monkeypatch):
    repo, binding = _enabled_binding(database)
    original = psycopg.errors.AdminShutdown("synthetic-original")

    class Disconnected(Provider):
        def catalog(self, *args, **kwargs):
            raise original

    monkeypatch.setattr(
        repo,
        "fail",
        lambda *_: (_ for _ in ()).throw(psycopg.InterfaceError("the connection is closed")),
    )
    with pytest.raises(ExportValidationError) as caught:
        KnowledgeOnesCollectionService(repo, lambda _: Disconnected()).collect_once(
            binding["id"], through=FIRST
        )
    assert caught.value.__cause__ is original
    assert recovery.transient_database_error(caught.value, "unused")


def test_credential_resolution_preserves_database_cause():
    error = psycopg.errors.AdminShutdown("synthetic")
    factory = ManagedOnesCollectionProviderFactory(
        lambda _: (_ for _ in ()).throw(error),
        allowed_hosts=("ones.example.test",),
        app_env="local",
    )
    with pytest.raises(ExportValidationError, match="identity_missing") as caught:
        factory({"provider_origin": "https://ones.example.test", "credential_ref": "synthetic"})
    assert caught.value.__cause__ is error


@pytest.mark.parametrize(
    "original", [ValueError("business rejection"), psycopg.errors.AdminShutdown("original")]
)
def test_unlock_failure_does_not_replace_original_error(original):
    @contextmanager
    def session():
        yield object()

    def execute(*_):
        raise psycopg.InterfaceError("the connection is closed")

    db = SimpleNamespace(
        engine="postgres",
        session=session,
        execute_one=lambda *_: {"acquired": True},
        execute=execute,
    )
    with pytest.raises(type(original)) as caught, source_lock(db, "synthetic-source"):
        raise original
    assert caught.value is original


@pytest.mark.parametrize("phase", ["STAGED", "CHUNKING", "INDEXING", "VERIFIED", "ACTIVATED"])
def test_pinned_run_resumes_phase_or_reads_committed_success(phase):
    store = FakeStore(phase, set())
    pipeline = ManagedSyncPipeline(
        store,
        collect_once=lambda _: pytest.fail("must not recollect"),
        chunk_base=lambda *_: None,
        index_base=lambda *_: None,
        activate=lambda _: {"run_id": "run", "phase": "ACTIVATED"},
    )
    # 激活后 active 查询已经为空，仍必须读取固定 run。
    store.active_collection = lambda _: pytest.fail("must use pinned run")
    assert pipeline.run_once("binding", resume_run_id="run")["phase"] == "ACTIVATED"


def test_cancelled_run_does_not_start_another_collection():
    store = FakeStore("CANCELLED", set())
    pipeline = ManagedSyncPipeline(
        store,
        collect_once=lambda _: pytest.fail("cancelled"),
        chunk_base=lambda *_: None,
        index_base=lambda *_: None,
        activate=lambda _: {},
    )
    with pytest.raises(ExportValidationError, match="knowledge_sync_cancelled"):
        pipeline.run_once("binding", resume_run_id="run")


def test_activation_readback_is_not_skipped_when_daemon_tick_is_not_due():
    @contextmanager
    def lock(_):
        yield

    store = SimpleNamespace(source_lock=lock, scheduled_due=lambda *_: False)
    pipeline = SimpleNamespace(run_once=lambda _, **kw: {"run_id": kw["resume_run_id"]})
    assert sync_ones_knowledge.execute_pipeline(
        store,
        "binding",
        pipeline,
        scheduled=True,
        checkpoint=recovery.RecoveryCheckpoint(run_id="run"),
    ) == {"run_id": "run"}


def test_daemon_loop_reads_pinned_success_even_before_next_tick(monkeypatch, tmp_path):
    stop = Event()
    checkpoint = recovery.RecoveryCheckpoint(run_id="run")
    settings, _key = _synthetic_file_key_settings(tmp_path)
    _stub_schema(monkeypatch, sync_ones_knowledge)
    repo = SimpleNamespace(binding=lambda _: {"enabled": 1}, scheduled_due=lambda *_: False)
    monkeypatch.setattr(sync_ones_knowledge, "ManagedActivationRepository", lambda _: repo)
    runtime = SimpleNamespace(
        database=sync_ones_knowledge.Database("unused"),
        knowledge_services=SimpleNamespace(resources=lambda: SimpleNamespace()),
    )
    monkeypatch.setattr(sync_ones_knowledge, "build_api_container", lambda *a, **kw: runtime)
    for name in ("EmbeddingClient", "QdrantClient"):
        monkeypatch.setattr(
            sync_ones_knowledge,
            name,
            lambda: SimpleNamespace(http=SimpleNamespace(close=lambda: None)),
        )
    monkeypatch.setattr(
        sync_ones_knowledge,
        "ManagedSyncSteps",
        lambda *a: SimpleNamespace(
            capacity=SimpleNamespace(check=lambda _: None),
            chunk=lambda *_: None,
            index=lambda *_: None,
        ),
    )
    monkeypatch.setattr(sync_ones_knowledge, "PlatformConfigRepository", lambda _: None)
    monkeypatch.setattr(
        sync_ones_knowledge,
        "EncryptedDbSecretProvider",
        lambda *a, **kw: SimpleNamespace(resolve=lambda _: "unused"),
    )
    monkeypatch.setattr(
        sync_ones_knowledge, "ManagedOnesCollectionProviderFactory", lambda *a, **kw: None
    )
    monkeypatch.setattr(sync_ones_knowledge, "ManagedSyncPipeline", lambda *a, **kw: object())
    calls = []

    def execute(*a, **kw):
        assert kw["checkpoint"].run_id == "run"
        calls.append("readback")
        stop.set()
        return {"run_id": "run", "phase": "ACTIVATED"}

    monkeypatch.setattr(sync_ones_knowledge, "execute_pipeline", execute)
    args = SimpleNamespace(mode="daemon", binding_code="synthetic", capacity_path=tmp_path)
    assert sync_ones_knowledge._execute(args, settings, stop, checkpoint) == 0
    assert calls == ["readback"] and checkpoint.run_id is None


def test_collection_resume_rechecks_start_tick_and_does_not_create_new_run(database):
    repo, binding = _enabled_binding(database)
    run = repo.begin_collection(binding["id"], "2024-01-01T01:00:00+00:00", through=FIRST)
    callbacks = []
    # 合成 Provider 返回空范围，最终业务校验拒绝；此前必须补记恢复 tick。
    with pytest.raises(ExportValidationError, match="knowledge_collection_empty_scope"):
        KnowledgeOnesCollectionService(repo, lambda _: Provider()).collect_once(
            binding["id"], resume_run_id=run["id"], on_run_started=callbacks.append
        )
    assert callbacks == [run["id"]]
    assert database.execute_one('select count(*) n from "knowledge.sync_run"')["n"] == 1


def test_vector_failure_retains_database_cause_even_when_error_state_write_fails(
    prepared, monkeypatch
):
    _db, service, snapshot = prepared
    original = psycopg.errors.AdminShutdown("synthetic-original")
    initial_state = service.repository.state

    def state(index, value, *args):
        if value == "FAILED":
            raise psycopg.InterfaceError("the connection is closed")
        return initial_state(index, value, *args)

    monkeypatch.setattr(service.repository, "state", state)
    monkeypatch.setattr(service.repository, "manifest", lambda _: (_ for _ in ()).throw(original))
    with pytest.raises(VectorError) as caught:
        service.build("synthetic-recovery-index", snapshot)
    assert caught.value.__cause__ is original
