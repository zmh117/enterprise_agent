"""Short-transaction coordination tests; PostgreSQL concurrency is verified separately."""

from dataclasses import replace

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from backend.tests.support.runtime import container
from backend.tests.support.code_answers import analysis_context, code_configuration, confirm


@pytest.fixture
def workspace(tmp_path):
    runtime = container()
    try:
        yield runtime, *code_configuration(runtime, tmp_path)
    finally:
        runtime.database.close()


def test_same_revision_readers_share_and_block_any_update(workspace):
    runtime, store, source, checkout, _ = workspace
    a = analysis_context(runtime, source, checkout, key="a")
    b = analysis_context(runtime, source, checkout, key="b")
    first = confirm(store, a, store.begin(a, "a"))
    second = confirm(store, b, store.begin(b, "b"))
    assert first["generation"] == second["generation"] == 0
    assert store.require_reader(a, first["id"])["state"] == "reading"
    assert store.require_reader(b, second["id"])["state"] == "reading"
    writer = analysis_context(runtime, source, checkout, key="writer", revision=101)
    with pytest.raises(CodeKnowledgeError, match="WORKSPACE_BUSY"):
        store.begin(writer, "writer")
    assert store.row("code_checkout", checkout["id"])["verified_revision"] == 100


def test_expired_reader_is_not_released_and_cancelling_one_keeps_other(workspace):
    runtime, store, source, checkout, _ = workspace
    a = analysis_context(runtime, source, checkout, key="a")
    b = analysis_context(runtime, source, checkout, key="b")
    first = confirm(store, a, store.begin(a, "a"))
    second = confirm(store, b, store.begin(b, "b"))
    store.db.execute(
        f"UPDATE {store.t('code_analysis')} SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
        (first["id"],),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_READ_GRANT_EXPIRED"):
        store.require_reader(a, first["id"])
    with pytest.raises(CodeKnowledgeError, match="CODE_EXECUTION_NOT_QUIESCED"):
        store.release_stopped(a, first["id"])
    store.db.execute(
        "UPDATE agent_runtime_invocation SET execution_quiesced_at=? WHERE invocation_id=?",
        ("2026-11-09T00:00:00+00:00", a.invocation_id),
    )
    store.release_stopped(a, first["id"])
    assert store.require_reader(b, second["id"])["read_released_at"] is None
    writer = analysis_context(runtime, source, checkout, key="writer", revision=101)
    with pytest.raises(CodeKnowledgeError, match="WORKSPACE_BUSY"):
        store.begin(writer, "writer")


def test_writer_blocks_new_readers_then_atomically_becomes_reader(workspace):
    runtime, store, source, checkout, _ = workspace
    a = analysis_context(runtime, source, checkout, key="a", revision=101)
    first = store.begin(a, "a")
    assert first["read_acquired_at"] is None
    assert store.row("code_checkout", checkout["id"])["writer_operation_id"] is not None
    b = analysis_context(runtime, source, checkout, key="b", revision=101)
    with pytest.raises(CodeKnowledgeError, match="WORKSPACE_BUSY"):
        store.begin(b, "b")
    first = confirm(store, a, first)
    assert first["generation"] == 1
    assert store.row("code_checkout", checkout["id"])["writer_operation_id"] is None
    second = confirm(store, b, store.begin(b, "b"))
    assert second["generation"] == 1
    assert store.require_reader(a, first["id"])["requested_revision"] == 101


def test_replay_single_active_analysis_and_context_identity(workspace):
    runtime, store, source, checkout, _ = workspace
    a = analysis_context(runtime, source, checkout)
    first = store.begin(a, "request")
    assert store.begin(a, "request")["id"] == first["id"]
    with pytest.raises(CodeKnowledgeError, match="CODE_IDEMPOTENCY_CONFLICT"):
        store.begin(replace(a, revision=101), "request")
    with pytest.raises(CodeKnowledgeError, match="CODE_ANALYSIS_ALREADY_ACTIVE"):
        store.begin(replace(a, revision=101), "different")
    with pytest.raises(CodeKnowledgeError, match="CODE_EXECUTION_MISMATCH"):
        store.begin(replace(a, owner_instance_id="other-owner"), "request")


def test_registration_rejects_nested_and_symlink_aliases(workspace):
    _, store, source, _, root = workspace
    (root / "mes" / "nested").mkdir()
    with pytest.raises(CodeKnowledgeError, match="CODE_CHECKOUT_OVERLAP"):
        store.register_checkout(
            source_id=source,
            root_key="code-svn-checkout",
            root=root,
            relative_dir="mes/nested",
            selected_paths=[""],
        )
    (root / "alias").symlink_to(root / "mes", target_is_directory=True)
    with pytest.raises(CodeKnowledgeError, match="CODE_CHECKOUT_PATH_INVALID"):
        store.register_checkout(
            source_id=source,
            root_key="code-svn-checkout",
            root=root,
            relative_dir="alias",
            selected_paths=[""],
        )
