"""Managed resource-scoped checkout uses the same operation and writer ledger."""

import json
from types import SimpleNamespace

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_client import (
    checkout_directory,
    registered_url,
    selection,
)
from app.modules.knowledge.infrastructure.code_checkout_jobs import CodeCheckoutJobs
from app.modules.knowledge.infrastructure.code_management_executor import CodeManagementExecutor
from app.modules.knowledge.infrastructure.code_result_buffer import CodeResultBuffer
from backend.tests.test_code_resources import setup as setup_fixture, create

setup = setup_fixture


@pytest.mark.parametrize("kind", ["empty", "directory", "file", "symlink", "dangling"])
def test_checkout_reservation_never_reuses_existing_target(tmp_path, kind):
    target = tmp_path / "checkout"
    if kind in {"empty", "directory"}:
        target.mkdir()
        if kind == "directory":
            (target / "keep").write_text("untouched")
    elif kind == "file":
        target.write_text("untouched")
    else:
        original = tmp_path / "original"
        if kind == "symlink":
            original.mkdir()
            (original / "keep").write_text("untouched")
        target.symlink_to(original, target_is_directory=True)
    identity = target.lstat()
    with pytest.raises(CodeKnowledgeError, match="^code_checkout_destination_exists$"):
        with checkout_directory(target):
            pytest.fail("must reject before writing")
    assert target.lstat() == identity
    if kind in {"directory", "symlink"}:
        assert (target / "keep").read_text() == "untouched"


def test_concurrent_checkout_reservations_have_only_one_owner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event

    target = tmp_path / "checkout"
    start, rejected = Barrier(2), Event()

    def attempt():
        start.wait(timeout=5)
        try:
            with checkout_directory(target):
                (target / "owned").write_text("complete")
                assert rejected.wait(timeout=5)
            return "success"
        except CodeKnowledgeError as exc:
            rejected.set()
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == ["code_checkout_destination_exists", "success"]
    assert (target / "owned").read_text() == "complete"


def test_failed_checkout_cleans_own_directory_and_preserves_failure(tmp_path):
    target, kept = tmp_path / "checkout", tmp_path / "keep"
    kept.mkdir()
    (kept / "file").write_text("untouched")
    with pytest.raises(CodeKnowledgeError, match="^CODE_SVN_UPDATE_TIMEOUT$"):
        with checkout_directory(target):
            (target / "partial").write_text("unfinished")
            (target / "external").symlink_to(kept, target_is_directory=True)
            raise CodeKnowledgeError("CODE_SVN_UPDATE_TIMEOUT")
    assert not target.exists()
    assert (kept / "file").read_text() == "untouched"


@pytest.mark.parametrize("fail", [True, False])
def test_replaced_checkout_is_never_cleaned_or_reported_complete(tmp_path, fail):
    target, original = tmp_path / "checkout", tmp_path / "original"
    expected = "CODE_SVN_UPDATE_TIMEOUT" if fail else "CODE_CHECKOUT_IDENTITY_CHANGED"
    with pytest.raises(CodeKnowledgeError, match=f"^{expected}$"):
        with checkout_directory(target):
            (target / "partial").write_text("unfinished")
            target.rename(original)
            target.mkdir()
            (target / "keep").write_text("untouched")
            if fail:
                raise CodeKnowledgeError(expected)
    assert (target / "keep").read_text() == "untouched"
    assert (original / "partial").read_text() == "unfinished"


def test_cleanup_failure_does_not_hide_checkout_failure(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("synthetic cleanup denied")

    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.code_checkout_client.shutil.rmtree", denied
    )
    with pytest.raises(CodeKnowledgeError, match="^CODE_SVN_UPDATE_TIMEOUT$"):
        with checkout_directory(tmp_path / "checkout"):
            raise CodeKnowledgeError("CODE_SVN_UPDATE_TIMEOUT")
    assert (tmp_path / "checkout").is_dir()


def test_checkout_directory_is_group_readable_without_changing_private_umask(tmp_path):
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, stat, sys
from pathlib import Path
from app.modules.knowledge.infrastructure.code_checkout_client import checkout_directory
os.umask(0o077)
path = Path(sys.argv[1])
with checkout_directory(path):
    assert stat.S_IMODE(path.stat().st_mode) == 0o750
    private = path.parent / 'private-config'
    private.write_text('synthetic')
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
""",
            str(tmp_path / "checkout"),
        ],
        check=True,
    )


@pytest.fixture
def management(setup, monkeypatch):
    runtime, source, _, root, service, registry = setup
    resource = create(service)
    jobs = CodeCheckoutJobs(runtime.database, runtime.knowledge_services.sources(), registry)
    buffer = CodeResultBuffer()
    state = {"revision": 2, "fail": False, "calls": 0, "browse_calls": []}
    info = {
        "repository_uuid": "00000000-0000-0000-0000-000000000001",
        "branch_path": "/trunk",
        "repository_root_url": "https://svn.invalid/repository",
    }

    class Client:
        def __init__(self, entry, auth, cancelled):
            self.source = SimpleNamespace(preflight=lambda revision: info)

        def browse(self, revision, *, path=""):
            state["calls"] += 1
            state["browse_calls"].append((revision, path))
            return {
                "revision": revision if revision is not None else state["revision"],
                "repository_uuid": info["repository_uuid"],
                "registration_hash": "a" * 64,
                "directories": ["set_server"],
                "files": ["README.md", "set_server/Order.cpp"],
            }

        def checkout(self, *, root, folder, job_id, revision, paths):
            state["calls"] += 1
            if state["fail"]:
                raise CodeKnowledgeError("CODE_SYNTHETIC_FAILURE")
            directory = root / folder
            directory.mkdir()
            (directory / ".svn").mkdir()
            (directory / "README.md").write_text("synthetic complete file")

    class Copy:
        def __init__(self, source, path, paths, physical_key):
            self.paths = paths

        def inspect(self, revision):
            return {
                "repository_uuid": info["repository_uuid"],
                "branch_path": "trunk",
                "operative_revision": revision,
                "selected_paths": self.paths,
                "file_count": 1,
                "bytes": 23,
                "mixed": False,
                "modified": False,
                "switched": False,
            }

    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.code_management_executor.WorkingCopyClient", Client
    )
    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.code_management_executor.SvnWorkingCopy", Copy
    )
    executor = CodeManagementExecutor(
        jobs,
        buffer,
        owner="synthetic-worker",
        auth_root=root,
        checkout_root=root,
        stopped=lambda: False,
    )
    return jobs, resource, executor, buffer, state, root


def browse(f, key="browse"):
    jobs, resource, executor, _, _, _ = f
    operation = jobs.submit_browse(
        actor_id="user_local_admin",
        resource_id=resource["id"],
        url="https://svn.invalid/repository/trunk",
        revision=None,
        request_key=key,
    )
    executor.execute(operation["id"])
    return jobs.get(operation["id"])


def submit(f, operation, folder="selected"):
    return f[0].submit_checkout(
        actor_id="user_local_admin",
        resource_id=f[1]["id"],
        browse_job_id=operation["id"],
        paths=["README.md", "set_server"],
        folder=folder,
        request_key="checkout-" + folder,
    )


def test_browse_has_files_and_directories_but_persists_only_bounded_metadata(management):
    jobs, _, _, buffer, _, _ = management
    operation = browse(management)
    assert operation["state"] == "succeeded"
    assert operation["result"]["file_count"] == 2
    # Raw file tree goes through the transient internal result endpoint only.
    stored = jobs.db.execute_one(
        f"SELECT result_json FROM {jobs.t('code_svn_operation')} WHERE id=?", (operation["id"],)
    )
    assert "Order.cpp" not in json.dumps(stored)
    assert buffer.get(
        operation["id"], operation["claim_version"], expected_hash=operation["result_hash"]
    )["files"] == ["README.md", "set_server/Order.cpp"]


def test_child_browse_inherits_root_identity_and_revision(management):
    jobs, resource, executor, _, state, _ = management
    root = browse(management)
    state["revision"] = 3
    args = dict(
        actor_id="user_local_admin",
        resource_id=resource["id"],
        browse_job_id=root["id"],
        path="set_server",
        request_key="child",
    )
    child = jobs.submit_browse_children(**args)
    assert jobs.submit_browse_children(**args)["id"] == child["id"]
    assert child["request"]["revision"] == 2
    assert child["source_id"] == root["source_id"]
    assert child["request"]["registration_hash"] == root["request"]["registration_hash"]
    executor.execute(child["id"])
    assert state["browse_calls"][-1] == (2, "set_server")
    child = jobs.get(child["id"])
    assert child["state"] == "succeeded"
    assert child["result"]["directory_path"] == "set_server"
    with pytest.raises(CodeKnowledgeError, match="CODE_CHECKOUT_BROWSE_REQUIRED"):
        jobs.submit_browse_children(
            **{**args, "browse_job_id": child["id"], "request_key": "nested"}
        )


@pytest.mark.parametrize("path", ["", "../outside", "/root", ".svn", "a/../b", "a\\b"])
def test_child_browse_rejects_invalid_path_without_enqueue(management, path):
    jobs, resource, _, _, state, _ = management
    root = browse(management)
    with pytest.raises(CodeKnowledgeError, match="CODE_PATH_INVALID"):
        jobs.submit_browse_children(
            actor_id="user_local_admin",
            resource_id=resource["id"],
            browse_job_id=root["id"],
            path=path,
            request_key="child",
        )
    assert state["calls"] == 1


@pytest.mark.parametrize("mismatch", ["actor", "resource", "failed", "draft_race"])
def test_child_browse_rejects_unrelated_root_or_changed_draft(management, monkeypatch, mismatch):
    jobs, resource, _, _, state, _ = management
    root = browse(management)
    if mismatch == "actor":
        original_get = jobs.get
        monkeypatch.setattr(
            jobs, "get", lambda identifier: {**original_get(identifier), "actor_id": "other"}
        )
    if mismatch == "failed":
        jobs.db.execute(
            f"UPDATE {jobs.t('code_svn_operation')} SET state='failed' WHERE id=?", (root["id"],)
        )
    original = jobs.draft

    def draft(resource_id, *, lock=False):
        result = original(resource_id, lock=lock)
        if mismatch == "resource" or (mismatch == "draft_race" and lock):
            return {**result, "revision_id": "another-revision"}
        return result

    monkeypatch.setattr(jobs, "draft", draft)
    with pytest.raises(
        CodeKnowledgeError, match="CODE_CHECKOUT_BROWSE_REQUIRED|CODE_CONFIGURATION_CHANGED"
    ):
        jobs.submit_browse_children(
            actor_id="user_local_admin",
            resource_id=resource["id"],
            browse_job_id=root["id"],
            path="set_server",
            request_key="child",
        )
    assert state["calls"] == 1


def test_large_recursive_inventory_is_not_loaded_for_directory_preview(tmp_path, monkeypatch):
    from app.modules.knowledge.infrastructure.code_checkout_client import WorkingCopyClient
    from app.modules.knowledge.infrastructure.code_svn import MAX_XML_BYTES, SvnCodeSource

    client = WorkingCopyClient.__new__(WorkingCopyClient)
    client.entry = {"repository_uuid": "synthetic-uuid"}
    client.source = SvnCodeSource(
        branch_url="https://svn.invalid/trunk",
        expected_uuid="synthetic-uuid",
        branch_path="/trunk",
        config_directory=tmp_path,
    )
    calls = []
    # The old recursive preview would exceed the exact existing XML cap.
    large = (
        b"<lists><list>"
        + b'<entry kind="file"><name>module/long-name.cpp</name></entry>' * 160000
        + b"</list></lists>"
    )
    assert len(large) > MAX_XML_BYTES

    def run(operation, args, *, timeout=60):
        calls.append((operation, args))
        if operation == "info":
            return b'<info><entry kind="dir" revision="2"><relative-url>^/trunk</relative-url><repository><uuid>synthetic-uuid</uuid></repository></entry></info>'
        if "--recursive" in args:
            return large
        if args[-1].endswith("/module@2"):
            return b'<lists><list><entry kind="file"><name>rule.cpp</name><size>12</size></entry></list></lists>'
        return b'<lists><list><entry kind="dir"><name>module</name></entry><entry kind="file"><name>README.md</name><size>10</size></entry></list></lists>'

    monkeypatch.setattr(client.source, "_run", run)
    assert client.browse(2)["directories"] == ["module"]
    assert client.browse(2, path="module")["files"] == ["module/rule.cpp"]
    assert all("--recursive" not in args for _, args in calls)
    assert all(
        args[args.index("--depth") + 1] == "immediates" for op, args in calls if op == "list"
    )


def test_directory_preview_rejects_nested_response_and_files(tmp_path, monkeypatch):
    from app.modules.knowledge.infrastructure.code_svn import SvnCodeSource

    source = SvnCodeSource(
        branch_url="https://svn.invalid/trunk",
        expected_uuid="uuid",
        branch_path="/trunk",
        config_directory=tmp_path,
    )
    monkeypatch.setattr(source, "_run", lambda op, args: b'<info><entry kind="file" /></info>')
    with pytest.raises(CodeKnowledgeError, match="CODE_BROWSE_DIRECTORY_REQUIRED"):
        source.directory_entries("file.cpp", 2)

    def run(op, args, *, timeout=60):
        return (
            b'<info><entry kind="dir" /></info>'
            if op == "info"
            else b'<lists><list><entry kind="file"><name>unrequested/deep.cpp</name></entry></list></lists>'
        )

    monkeypatch.setattr(source, "_run", run)
    with pytest.raises(CodeKnowledgeError, match="code_svn_response_invalid"):
        source.directory_entries("module", 2)


def test_checkout_selection_is_pinned_and_atomic_writer_is_released_after_verification(management):
    jobs, _, executor, _, state, root = management
    browsed = browse(management)
    state["revision"] = 3
    operation = submit(management, browsed)
    checkout = jobs.row("code_checkout", operation["checkout_id"])
    assert checkout["state"] == "preparing" and checkout["writer_operation_id"] == operation["id"]
    assert submit(management, browsed)["id"] == operation["id"]
    executor.execute(operation["id"])
    checkout = jobs.row("code_checkout", operation["checkout_id"])
    assert checkout["state"] == "ready" and checkout["verified_revision"] == 2
    assert checkout["writer_operation_id"] is None and checkout["physical_key"]
    assert (root / "selected/README.md").read_text() == "synthetic complete file"
    assert jobs.get(operation["id"])["quiesced_at"]
    assert state["calls"] == 2
    with pytest.raises(CodeKnowledgeError):
        executor.execute(operation["id"])
    assert state["calls"] == 2


def test_failed_checkout_marks_invalid_without_replaying_or_stealing_writer(management):
    jobs, _, executor, _, state, _ = management
    operation = submit(management, browse(management))
    state["fail"] = True
    executor.execute(operation["id"])
    row = jobs.get(operation["id"])
    assert row["state"] == "failed" and row["quiesced_at"]
    checkout = jobs.row("code_checkout", operation["checkout_id"])
    assert checkout["state"] == "invalid" and checkout["writer_operation_id"] is None


@pytest.mark.parametrize("fail", [True, False])
def test_visible_checkout_remains_preparing_until_final_verification(management, monkeypatch, fail):
    from app.modules.knowledge.infrastructure import code_management_executor as execution

    jobs, _, executor, _, _, root = management
    operation = submit(management, browse(management))
    inspect = execution.SvnWorkingCopy.inspect

    def verify(copy, revision):
        assert (root / "selected/README.md").is_file()
        checkout = jobs.row("code_checkout", operation["checkout_id"])
        assert checkout["state"] == "preparing"
        assert checkout["writer_operation_id"] == operation["id"]
        if fail:
            raise CodeKnowledgeError("code_checkout_verification_failed")
        return inspect(copy, revision)

    monkeypatch.setattr(execution.SvnWorkingCopy, "inspect", verify)
    executor.execute(operation["id"])
    checkout = jobs.row("code_checkout", operation["checkout_id"])
    assert checkout["state"] == ("invalid" if fail else "ready")
    assert jobs.get(operation["id"])["state"] == ("failed" if fail else "succeeded")
    assert checkout["writer_operation_id"] is None


def test_expired_running_management_is_never_reclaimed_as_stopped(management):
    jobs, _, _, _, _, _ = management
    operation = submit(management, browse(management))
    row = jobs.claim_management(operation["id"], owner="original")
    jobs.db.execute(
        f"UPDATE {jobs.t('code_svn_operation')} SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
        (row["id"],),
    )
    with pytest.raises(CodeKnowledgeError):
        jobs.claim_management(row["id"], owner="another")
    assert jobs.row("code_checkout", operation["checkout_id"])["writer_operation_id"] == row["id"]


def test_registration_and_selection_reject_arbitrary_targets(setup):
    registry = setup[-1]
    with pytest.raises(CodeKnowledgeError):
        registered_url(registry, "https://arbitrary.invalid/trunk")
    with pytest.raises(CodeKnowledgeError):
        registered_url(registry, "https://user:synthetic@svn.invalid/repository/trunk")
    for paths in (["../other"], ["set_server", "set_server/Order.cpp"]):
        with pytest.raises(CodeKnowledgeError):
            selection(paths, ["set_server", "set_server/Order.cpp"])


def test_worker_recovery_requires_matching_actual_stop_proof(management):
    from app.cli.code_source_worker import _recover_stopped_operations
    from app.modules.knowledge.infrastructure.code_executor_lock import execution_lock

    jobs, _, _, _, state, root = management
    operation = submit(management, browse(management))
    row = jobs.claim_management(operation["id"], owner="original")
    jobs.db.execute(
        f"UPDATE {jobs.t('code_svn_operation')} SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
        (row["id"],),
    )
    _recover_stopped_operations(jobs, jobs, root)
    assert jobs.get(row["id"])["state"] == "running"
    with execution_lock(root, "svn", row["id"]) as proof:
        proof.bind(row)
        _recover_stopped_operations(jobs, jobs, root)
        assert jobs.get(row["id"])["state"] == "running"
    _recover_stopped_operations(jobs, jobs, root)
    assert jobs.get(row["id"])["error_code"] == "CODE_EXECUTOR_STOPPED"
    checkout = jobs.row("code_checkout", row["checkout_id"])
    assert checkout["state"] == "invalid" and checkout["writer_operation_id"] is None
    assert state["calls"] == 1  # Only browse, never automatic checkout/update replay.


@pytest.mark.parametrize("stale_registration", [False, True])
def test_existing_checkout_registration_is_read_only_and_refuses_active_readers(
    setup, monkeypatch, stale_registration
):
    from app.cli.register_code_checkout import register_existing
    from backend.tests.support.code_answers import analysis_context, confirm
    from app.modules.knowledge.infrastructure.code_analysis_store import CodeAnalysisStore

    runtime, source, checkout, root, _, registry_file = setup
    prior_operations = runtime.database.execute('SELECT id FROM "knowledge.code_svn_operation"')
    entry = json.loads(registry_file.read_text())["synthetic"]
    inspected = []

    class ExistingClient:
        def __init__(self, entry, auth):
            self.source = SimpleNamespace(
                head=lambda: 100,
                preflight=lambda version: {"repository_root_url": "https://svn.invalid/repository"},
            )

    class ExistingCopy:
        def __init__(self, source, directory, paths, physical_key):
            inspected.append((directory, paths, physical_key))

        def inspect(self, revision=None):
            return {"operative_revision": 100}

    monkeypatch.setattr("app.cli.register_code_checkout.WorkingCopyClient", ExistingClient)
    monkeypatch.setattr("app.cli.register_code_checkout.SvnWorkingCopy", ExistingCopy)
    args = dict(entry=entry, root=root, auth_root=root, directory="mes", paths=[""])
    (root / "mes" / ".svn").mkdir()
    if stale_registration:
        runtime.database.execute(
            'UPDATE "knowledge.code_checkout" SET physical_key=? WHERE id=?',
            ("f" * 64, checkout["id"]),
        )
        args["repair_identity"] = True
        from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity

        def interrupted(directory, *, create):
            persistent_identity(directory, create=create)
            raise CodeKnowledgeError("CODE_SYNTHETIC_INTERRUPTION")

        with monkeypatch.context() as patch:
            patch.setattr("app.cli.register_code_checkout.persistent_identity", interrupted)
            with pytest.raises(CodeKnowledgeError, match="CODE_SYNTHETIC_INTERRUPTION"):
                register_existing(runtime.database, **args)
        inspected.clear()
    result = register_existing(runtime.database, **args)
    assert result["checkout_id"] == checkout["id"] and result["source_id"] == source
    assert len(inspected) == 1
    from app.modules.knowledge.infrastructure.code_checkout_identity import persistent_identity

    saved = runtime.database.execute_one(
        'SELECT physical_key FROM "knowledge.code_checkout" WHERE id=?', (checkout["id"],)
    )
    assert saved["physical_key"] == persistent_identity(root / "mes")
    # Idempotent restart after an identity marker has already been persisted.
    register_existing(runtime.database, **args)
    assert len(inspected) == 2
    assert (
        runtime.database.execute('SELECT id FROM "knowledge.code_svn_operation"')
        == prior_operations
    )
    store = CodeAnalysisStore(runtime.database, authorize=lambda context: None)
    ctx = analysis_context(runtime, source, checkout)
    pending = store.begin(ctx, "active")
    with pytest.raises(CodeKnowledgeError, match="WORKSPACE_BUSY"):
        register_existing(runtime.database, **args)
    confirm(store, ctx, pending)
    with pytest.raises(CodeKnowledgeError, match="WORKSPACE_BUSY"):
        register_existing(runtime.database, **args)
    assert len(inspected) == 2


def test_checkout_space_is_bounded_before_subprocess(tmp_path, monkeypatch):
    from app.modules.knowledge.infrastructure.code_working_copy import preflight_checkout_space

    source = SimpleNamespace(
        inventory=lambda path, revision: [{"kind": "file", "size_bytes": 1024}]
    )
    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.code_working_copy.shutil.disk_usage",
        lambda root: SimpleNamespace(free=1),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_CHECKOUT_DISK_LIMIT"):
        preflight_checkout_space(source, tmp_path, ["set_server"], 100)
    source.inventory = lambda path, revision: [{"kind": "file", "size_bytes": 21 * 1024**3}]
    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.code_working_copy.shutil.disk_usage",
        lambda root: SimpleNamespace(free=100 * 1024**3),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_CHECKOUT_DISK_LIMIT"):
        preflight_checkout_space(source, tmp_path, ["set_server"], 100)
