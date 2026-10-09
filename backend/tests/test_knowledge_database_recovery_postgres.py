"""显式启用的隔离 PostgreSQL 重启验收；只允许测试归属临时容器。"""

from datetime import datetime
import json
import os
import subprocess
from threading import Event
import time
import uuid
from zoneinfo import ZoneInfo

import pytest
from psycopg.conninfo import conninfo_to_dict

from app.cli import collect_ones_knowledge
from app.cli.knowledge_database_recovery import RecoveryCheckpoint, recover_database
from app.modules.knowledge.application.ones_collection import CollectionPage
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from backend.tests.test_knowledge_keep_ids import dataset
from backend.tests.test_knowledge_ones_collection import Provider


_CONTAINER = os.getenv("KNOWLEDGE_RECOVERY_TEST_CONTAINER", "")
_DSN = os.getenv("KNOWLEDGE_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(
    not (_CONTAINER and _DSN), reason="requires owned disposable PostgreSQL"
)


def docker(*args):
    assert _CONTAINER.startswith("ea-kb-recovery-test-")
    return subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=45
    ).stdout.strip()


def ready():
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", _CONTAINER, "pg_isready", "-U", "postgres"],
            capture_output=True,
            timeout=3,
        )
        if result.returncode == 0:
            return
        time.sleep(0.2)
    pytest.fail("isolated PostgreSQL did not become ready")


@pytest.fixture
def collection(monkeypatch, tmp_path):
    # inspect 仅读取测试所有权标签，不读取容器环境或真实凭据。
    assert (
        docker(
            "inspect", "--format", '{{ index .Config.Labels "enterprise-agent.test" }}', _CONTAINER
        )
        == "knowledge-db-recovery"
    )
    target = conninfo_to_dict(_DSN)
    assert target["host"] == "127.0.0.1" and target["dbname"] == "knowledge_recovery_test"
    assert docker("port", _CONTAINER, "5432/tcp") == "127.0.0.1:" + target["port"]
    ready()
    database = Database(_DSN)
    try:
        Migrator(database, default_migrations_dir(), migrator_build="knowledge-recovery-test").run()
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        suffix = uuid.uuid4().hex[:12]
        repo = SyncRepository(database)
        binding = repo.configure(
            code="recovery_" + suffix,
            source_code="source_" + suffix,
            configuration={
                "base_codes": {
                    kind: kind + "_" + suffix for kind in ("defect", "ticket", "requirement")
                },
                "resource_ids": [],
                "collector": {
                    "provider_origin": "https://ones.example.test",
                    "team_id": "team-1",
                    "project_ids": ["project_id"],
                    "issue_types": {
                        "defect": ["type_1"],
                        "ticket": ["type_2"],
                        "requirement": ["type_3"],
                    },
                    "child_type_ids": ["type_4"],
                    "first_date": today.isoformat(),
                    "credential_ref": "secret://platform/synthetic-collector",
                },
            },
            expected_revision=0,
        )
        repo.set_collection_enabled(binding["id"], enabled=True, expected_revision=1)
    finally:
        database.close()
    rows = dataset(tmp_path)
    provider = Provider()
    listing = json.loads((tmp_path / "缺陷_list.jsonl").read_text())
    provider.counts["type_1", today, today] = 1
    provider.pages["type_1", today, today, None] = CollectionPage((listing,), 1, False, None)
    provider.details[rows["缺陷"]["uuid"]] = rows["缺陷"]
    fields = json.loads((tmp_path / "字段字典.json").read_text())["fields"]
    provider.catalog = lambda *args, **kw: ({field["uuid"]: field for field in fields}, {})
    monkeypatch.setattr(
        collect_ones_knowledge,
        "EncryptedDbSecretProvider",
        lambda *a, **kw: type("Secrets", (), {"resolve": lambda *_: "unused"})(),
    )
    monkeypatch.setattr(
        collect_ones_knowledge,
        "ManagedOnesCollectionProviderFactory",
        lambda *a, **kw: lambda _: provider,
    )
    return Settings(database_dsn=_DSN, environment="local"), binding, provider, today


def test_restart_after_page_commit_resumes_same_run_and_keeps_candidate_idempotent(
    collection, monkeypatch
):
    settings, binding, provider, today = collection
    complete_day = SyncRepository.complete_collection_day
    restarted = False
    checkpoint, events = RecoveryCheckpoint(), []

    def restart_before_day_commit(repo, run_id, day, counts):
        nonlocal restarted
        if not restarted:
            restarted = True
            assert repo.run(run_id)["checkpoint_json"]["collection_next_day"] == today.isoformat()
            assert len(repo.staged_collection_ids(run_id)) == 1
            docker("restart", "--time", "1", _CONTAINER)
            ready()
        return complete_day(repo, run_id, day, counts)

    monkeypatch.setattr(SyncRepository, "complete_collection_day", restart_before_day_commit)
    stop = Event()
    monkeypatch.setattr(stop, "wait", lambda _: False)
    result = recover_database(
        lambda: collect_ones_knowledge._collect_once(settings, binding["id"], stop, checkpoint),
        dsn=_DSN,
        stop=stop,
        emit=lambda event, value: events.append(event),
        prefix="knowledge_collection",
    )
    assert restarted and result["phase"] == "STAGED" and result["run_id"] == checkpoint.run_id
    assert provider.fetched == ["item_1"]  # 未完成日重枚举，但不重拉已 staged 详情。
    assert events == ["knowledge_collection_database_retry_pending"]
    database = Database(_DSN)
    try:
        assert (
            database.execute_one(
                "select count(*) n from knowledge.sync_run where binding_id=?", (binding["id"],)
            )["n"]
            == 1
        )
        assert (
            database.execute_one(
                "select count(*) n from knowledge.sync_candidate where run_id=?",
                (result["run_id"],),
            )["n"]
            == 1
        )
        assert (
            SyncRepository(database).run(result["run_id"])["checkpoint_json"]["collection_next_day"]
            > today.isoformat()
        )
        # 新连接实际重新取得来源锁，未提前发布候选内容。
        with SyncRepository(database).source_lock(binding["source_id"]):
            assert (
                database.execute_one(
                    "select count(*) n from knowledge.knowledge_base_document where document_id in (select id from knowledge.document where source_id=?)",
                    (binding["source_id"],),
                )["n"]
                == 0
            )
    finally:
        database.close()


def test_database_down_at_start_recovers_without_starting_second_run(collection):
    settings, binding, provider, _today = collection
    docker("stop", "--time", "1", _CONTAINER)
    events = []

    def retry(event, value):
        events.append(event)
        docker("start", _CONTAINER)
        ready()

    try:
        stop, checkpoint = Event(), RecoveryCheckpoint()
        result = recover_database(
            lambda: collect_ones_knowledge._collect_once(settings, binding["id"], stop, checkpoint),
            dsn=_DSN,
            stop=stop,
            emit=retry,
            prefix="knowledge_collection",
        )
        assert result["phase"] == "STAGED" and provider.fetched == ["item_1"]
        assert events == ["knowledge_collection_database_retry_pending"]
    finally:
        docker("start", _CONTAINER)
        ready()
