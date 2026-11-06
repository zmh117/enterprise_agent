"""Independent synthetic fixtures, not extraction or real MES acceptance."""

from copy import deepcopy
import json

import pytest

from app.modules.knowledge.domain.code_contracts import (
    CONTRACT_VERSION,
    KNOWLEDGE,
    CodeKnowledgeError,
    validate,
)
from app.modules.knowledge.domain.code_package import (
    EvidenceSource,
    decode_package,
    encode_package,
    sha256,
    verify_candidate,
)
from app.modules.knowledge.domain.code_history import compare_records, history_intervals
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, knowledge_id
from app.modules.knowledge.infrastructure.storage import table
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator


def fixture(revision=100, source_snapshot_id="source-snapshot"):
    # Manually specified truth: one rule is removed in 101 and restored in 102.
    text = (
        "if (a.empty()) return reject;\nreturn accepted;\n"
        if revision != 101
        else "return accepted;\n"
    )
    file = EvidenceSource(
        "set_server/work_order.cpp", sha256(text.encode()), sha256(text.encode()), text
    )
    evidence = dict(
        id="ev",
        source_snapshot_id=source_snapshot_id,
        file_id="file",
        path=file.path,
        symbol="publish",
        start_line=1,
        end_line=len(text.splitlines()),
        raw_hash=file.raw_hash,
        representation_hash=file.representation_hash,
        excerpt_hash=sha256(text.encode()),
    )
    fact = dict(description="请求已受理，完成结果未知", phase="accepted", evidence_ids=["ev"])
    guard = dict(
        op="predicate",
        expression="a is not empty" if revision != 101 else "no a restriction",
        null_semantics="distinct_from_empty",
        checked_at="request",
        evidence_ids=["ev"],
    )
    record = dict(
        business_key="factory.work_order.publish",
        identity_state="confirmed",
        kind="operation",
        role="backend",
        title="工单发布",
        fact_class="backend_behavior",
        summary="合成规则",
        object_version=None,
        states=[],
        trigger="publish",
        guard=guard,
        check_order=[],
        effects=[],
        outcomes=[fact],
        success_boundary=fact,
        configuration=[],
        evidence_ids=["ev"],
        required_runtime_facts=[],
        coverage="analyzed",
        unknowns=[],
    )
    manifest = dict(
        contract_version=CONTRACT_VERSION,
        source_snapshot_id=source_snapshot_id,
        source_ref=dict(
            kind="svn",
            repository_uuid="test-repository",
            branch_path="/trunk",
            revision=revision,
            manifest_hash="0" * 64,
        ),
        build_id="build",
        work_unit_id="unit",
        scope_hash="1" * 64,
        config_hash="2" * 64,
    )
    package = {
        "manifest.json": manifest,
        "knowledge.jsonl": [record],
        "evidence.jsonl": [evidence],
        "relations.jsonl": [],
        "coverage.json": {
            "entries": [
                dict(
                    entry_id="publish",
                    role="backend",
                    status="analyzed",
                    knowledge_keys=[record["business_key"]],
                    unknowns=[],
                )
            ],
            "unknowns": [],
        },
        "changes.json": {"removed_keys": [], "identity_unresolved": []},
    }
    return package, {"file": file}


def test_envelope_roundtrip_and_independent_reversal():
    records = []
    for revision, expected in [
        (100, "a is not empty"),
        (101, "no a restriction"),
        (102, "a is not empty"),
    ]:
        package, sources = fixture(revision)
        candidate = decode_package(encode_package(package))
        result = verify_candidate(
            candidate,
            expected_manifest=package["manifest.json"],
            sources=sources,
            expected_entries={"publish"},
        )
        assert result == dict(
            machine_valid=True,
            activation_blocked=False,
            business_verified=False,
            dependency_requests=[],
            knowledge_count=1,
            evidence_count=1,
            relation_count=0,
            removed_keys=[],
            removal_evidence=[],
        )
        assert candidate["knowledge.jsonl"][0]["guard"]["expression"] == expected
        records.append(candidate["knowledge.jsonl"][0])
    assert (
        compare_records(records[0], records[2], old_relations=[], new_relations=[])[
            "classification"
        ]
        == "unchanged"
    )
    checks = {
        rev: {
            **compare_records(records[i], records[i + 1], old_relations=[], new_relations=[]),
            "from_revision": rev - 1,
        }
        for i, rev in enumerate((101, 102))
    }
    history = history_intervals(
        lower=100, upper=102, relevant_revisions=[101, 102], checked=checks, ledger_complete=True
    )
    assert [item["changed_at_revision"] for item in history["changes"]] == [101, 102]
    assert history["complete"]
    missing = history_intervals(
        lower=100, upper=102, relevant_revisions=[101, 102], checked={}, ledger_complete=True
    )
    assert not missing["complete"] and len(missing["unresolved_intervals"]) == 2
    unchecked = history_intervals(
        lower=100, upper=102, relevant_revisions=[101, 102], checked=checks, ledger_complete=False
    )
    assert not unchecked["complete"] and all(
        item["changed_at_revision"] is None for item in unchecked["changes"]
    )


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda p: p["evidence.jsonl"][0].update(start_line=50), "code_evidence_lines_invalid"),
        (
            lambda p: p["evidence.jsonl"][0].update(raw_hash="f" * 64),
            "code_evidence_digest_mismatch",
        ),
        (
            lambda p: p["knowledge.jsonl"][0].update(evidence_ids=["missing"]),
            "code_evidence_reference_missing",
        ),
        (lambda p: p["manifest.json"].update(build_id="other"), "code_candidate_binding_mismatch"),
        (
            lambda p: p["knowledge.jsonl"].append(deepcopy(p["knowledge.jsonl"][0])),
            "code_duplicate_identity",
        ),
    ],
)
def test_candidate_rejects_tampering(mutation, code):
    package, sources = fixture()
    expected = deepcopy(package["manifest.json"])
    mutation(package)
    with pytest.raises(CodeKnowledgeError, match=code):
        verify_candidate(
            package, expected_manifest=expected, sources=sources, expected_entries={"publish"}
        )


def test_unknown_is_not_permission_and_schema_is_closed():
    package, sources = fixture()
    record = package["knowledge.jsonl"][0]
    record["unknowns"] = [
        dict(code="macro_unresolved", description="条件编译未核实", critical=True)
    ]
    record["guard"] = dict(op="unknown", reason="宏定义未核实")
    validate(record, KNOWLEDGE)
    assert verify_candidate(
        package,
        expected_manifest=package["manifest.json"],
        sources=sources,
        expected_entries={"publish"},
    )["activation_blocked"]
    record["activate"] = True
    with pytest.raises(CodeKnowledgeError):
        validate(record, KNOWLEDGE)
    with pytest.raises(CodeKnowledgeError):
        decode_package(b'{"entries":[],"entries":[]}')


@pytest.fixture
def database():
    db = Database("sqlite:///:memory:")
    Migrator(db, default_migrations_dir(), migrator_build="code-test").run()
    yield db
    db.close()


def test_repository_history_uses_members_and_preserves_identity(database):
    repo = CodeRepository(database)
    ids = repo.register(code="test-code", base_code="test-base", config={"components": ["backend"]})
    source_id, base_id = ids["source_id"], ids["knowledge_base_id"]
    snapshots = []
    for revision in (100, 101, 102):
        manifest = {"files": [str(revision)]}
        ref = dict(
            kind="svn",
            repository_uuid="test",
            branch_path="/trunk",
            revision=revision,
            manifest_hash=digest(manifest),
        )
        source = repo.freeze_source(source_id, ref, manifest)
        build = repo.new_build(
            source_id, source, purpose="history", configuration={"contract": CONTRACT_VERSION}
        )
        package, _ = fixture(revision, source)
        repo.store_candidate(build["snapshot_id"], package)
        # Test fixture readiness only; production readiness belongs to index/validation controller.
        database.execute(
            f"update {table(database, 'code_snapshot')} set state='READY' where id=?",
            (build["snapshot_id"],),
        )
        snapshots.append(build["snapshot_id"])
    document_id = knowledge_id(source_id, "factory.work_order.publish")
    r100 = repo.read_member(base_id, snapshots[0], document_id)
    r101 = repo.read_member(base_id, snapshots[1], document_id)
    assert r100["knowledge"]["guard"]["expression"] == "a is not empty"
    assert r101["knowledge"]["guard"]["expression"] == "no a restriction"
    assert r100["revision_id"] != r101["revision_id"]
    assert repo.resolve(base_id, {"kind": "svn", "revision": 100})["snapshot_id"] == snapshots[0]
    assert repo.resolve(base_id, {"kind": "svn", "revision": 99})["status"] == "BUILD_REQUIRED"
    assert repo.resolve(base_id, None)["status"] == "VERSION_REQUIRED"
    with pytest.raises(CodeKnowledgeError):
        repo.read_member("other-base", snapshots[0], document_id)
    with pytest.raises(CodeKnowledgeError, match="immutable"):
        repo.store_candidate(snapshots[0], package)
    assert (
        database.execute_one(f"select count(*) as n from {table(database, 'document')}")["n"] == 1
    )
    assert (
        database.execute_one(f"select current_revision_id from {table(database, 'document')}")[
            "current_revision_id"
        ]
        is None
    )
    assert not database.execute("PRAGMA foreign_key_check")


def test_source_admission_encoding_boundaries_and_stability(tmp_path):
    from app.modules.knowledge.infrastructure.code_source import (
        LocalCodeCollector,
        relative_path,
    )

    root = tmp_path.resolve()
    for component in ("set_server", "set_web/EBR", "set_web/JTH", "set_web/EBR_SPLIT"):
        (root / component).mkdir(parents=True)
    (root / "set_server/main.cpp").write_bytes("// 工单\r\nreturn accepted;\r\n".encode("gb18030"))
    (root / "set_web/EBR/order.vue").write_text("<template>工单</template>\n")
    (root / "set_web/JTH/group.ts").write_text("export const application = 2;\n")
    (root / "set_web/EBR_SPLIT/excluded.js").write_text("excluded")
    (root / "set_server/config.cpp").write_text("must not be read")
    (root / "set_server/synthetic.cpp").write_text('const password = "synthetic-fixture";')
    (root / "set_server/undecodable.cpp").write_bytes(b"\xff")
    (root / "set_server/link.cpp").symlink_to(root / "set_web/EBR_SPLIT/excluded.js")
    collector = LocalCodeCollector(root)
    frozen = collector.freeze()
    assert len(frozen.files) == 3
    assert {
        "path": "set_server/undecodable.cpp",
        "reason": "code_source_encoding_unknown",
    } in frozen.manifest["excluded"]
    assert frozen.source_ref["svn_revision"] is None
    entry = next(item for item in frozen.manifest["files"] if item["path"].endswith("main.cpp"))
    assert entry["encoding"] == "gb18030" and entry["lines"] == 2
    assert frozen.files[entry["file_id"]].text == "// 工单\nreturn accepted;\n"
    assert all("EBR_SPLIT" not in item.path for item in frozen.files.values())
    for path in ("/tmp/x", "../x", "set_server/../x", "set_server\\x", "set_server//x"):
        with pytest.raises(CodeKnowledgeError):
            relative_path(path)
    (root / "set_server/main.cpp").write_text("changed")
    with pytest.raises(CodeKnowledgeError, match="changed"):
        collector.verify_stable(frozen.manifest)


def test_source_symlink_parent_cannot_escape(tmp_path):
    from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector

    root = tmp_path.resolve() / "source"
    outside = tmp_path.resolve() / "outside"
    (root / "set_server").mkdir(parents=True)
    (outside / "EBR").mkdir(parents=True)
    (outside / "JTH").mkdir(parents=True)
    (root / "set_web").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CodeKnowledgeError, match="link"):
        LocalCodeCollector(root).freeze()


def test_svn_log_preserves_reversal_copy_delete_and_properties():
    from app.modules.knowledge.infrastructure.code_svn import parse_log, xml_document

    data = b"""<log><logentry revision="101"><paths>
    <path action="M" kind="file" text-mods="true" prop-mods="false">/trunk/set_server/order.cpp</path>
    <path action="A" copyfrom-path="/trunk/old.cpp" copyfrom-rev="100" prop-mods="true">/trunk/new.cpp</path>
    </paths><msg>Commit text is not evidence</msg></logentry>
    <logentry revision="102"><paths><path action="M">/trunk/set_server/order.cpp</path>
    <path action="D">/trunk/old.cpp</path><path action="M">/other/private.cpp</path></paths></logentry></log>"""
    commits = parse_log(data, lower=100, upper=102, branch_path="/trunk")
    assert [c["revision"] for c in commits] == [101, 102]
    assert commits[0]["paths"][1]["copy_from_revision"] == 100
    assert commits[0]["paths"][1]["properties_modified"] == "true"
    assert len(commits[1]["paths"]) == 2
    assert "Commit text" not in str(commits)
    with pytest.raises(CodeKnowledgeError):
        xml_document(b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><x>&x;</x>')


def test_build_readiness_partial_index_and_late_activation(database):
    from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository

    repo, builds = CodeRepository(database), CodeBuildRepository(database)
    ids = repo.register(code="build-code", base_code="build-base", config={"svn_verified": True})
    source_id = ids["source_id"]
    manifest = {"files": ["synthetic"]}
    ref = dict(
        kind="local_bundle", bundle_id="baseline", manifest_hash=digest(manifest), svn_revision=None
    )
    source = repo.freeze_source(source_id, ref, manifest)
    first = repo.new_build(source_id, source, purpose="baseline", configuration={"version": 1})
    lease = builds.claim(first["build_id"])
    for stage in ("QUEUED", "SOURCE_READY", "EXTRACTING", "VALIDATING"):
        builds.advance(first["build_id"], lease, stage)
    validation = dict(machine_valid=True, activation_blocked=False, business_verified=True)
    with pytest.raises(CodeKnowledgeError, match="incomplete"):
        builds.make_ready(
            first["build_id"],
            lease,
            validation=validation,
            expected_points={"one": "hash"},
            visible_points={},
        )
    assert repo.binding(source_id)["active_snapshot_id"] is None
    builds.make_ready(
        first["build_id"],
        lease,
        validation=validation,
        expected_points={"one": "hash"},
        visible_points={"one": "hash"},
    )
    with pytest.raises(CodeKnowledgeError, match="lease_lost"):
        builds.activate(first["build_id"], lease + 1)
    builds.activate(first["build_id"], lease)
    assert repo.binding(source_id)["active_snapshot_id"] == first["snapshot_id"]
    assert builds.get(first["build_id"])["stage"] == "ACTIVATED"


def test_bounded_idempotent_history_demand_and_ledger(database):
    from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository

    repo, builds = CodeRepository(database), CodeBuildRepository(database)
    ids = repo.register(
        code="history-code", base_code="history-base", config={"svn_verified": True}
    )
    source_id = ids["source_id"]
    assert builds.demand(source_id, 100, "requester")["status"] == "BUILD_REQUIRED"
    database.execute(
        f"update {table(database, 'code_binding')} set enabled=1,demand_enabled=1 where source_id=?",
        (source_id,),
    )
    result = builds.demand(source_id, 100, "requester")
    assert result == builds.demand(source_id, 100, "other-authorized-requester")
    for revision in range(101, 120):
        assert builds.demand(source_id, revision, "requester")["status"] == "BUILD_PENDING"
    assert builds.demand(source_id, 120, "requester") == {
        "status": "BUILD_REQUIRED",
        "reason": "queue_full",
    }
    builds.record_commits(
        source_id,
        config_hash=repo.binding(source_id)["config_hash"],
        after=100,
        target=102,
        repository_uuid="test",
        commits=[{"revision": 101, "paths": []}, {"revision": 102, "paths": []}],
    )
    assert repo.binding(source_id)["collected_revision"] == 102
    assert repo.binding(source_id)["active_snapshot_id"] is None
    assert (
        database.execute_one(
            f"select count(*) as n from {table(database, 'code_commit')} where analysis_state='PENDING'"
        )["n"]
        == 2
    )


def test_new_skills_are_assignable_but_not_default():
    from pathlib import Path
    from app.modules.agent.infrastructure.skill_loader import SkillLoader

    loader = SkillLoader(Path(__file__).resolve().parents[2] / ".claude/skills")
    for name in ("code-business-query", "extract-business-knowledge"):
        assert name not in loader.load()
        assert loader.load((name,))[name]
        assert next(row for row in loader.catalog() if row["code"] == name)["assignable"]


def test_behavior_pages_preserve_root_and_detect_revocation(database):
    from app.modules.knowledge.application.code_behavior import CodeBehaviorReader

    repo = CodeRepository(database)
    ids = repo.register(code="relations-code", base_code="relations-base", config={})
    source_id, base_id = ids["source_id"], ids["knowledge_base_id"]
    snapshots = []
    for revision in (100, 101):
        manifest = {"revision": revision}
        source = repo.freeze_source(
            source_id,
            dict(
                kind="svn",
                repository_uuid="test",
                branch_path="/trunk",
                revision=revision,
                manifest_hash=digest(manifest),
            ),
            manifest,
        )
        build = repo.new_build(source_id, source, purpose="history", configuration={})
        package, _ = fixture(revision, source)
        root = package["knowledge.jsonl"][0]
        for index in range(55):
            node = deepcopy(root)
            node["business_key"] = f"factory.recipe.rule{index}"
            node["kind"] = "rule"
            package["knowledge.jsonl"].append(node)
            package["relations.jsonl"].append(
                dict(
                    id=f"relation-{index:03d}",
                    from_key=root["business_key"],
                    to_key=node["business_key"],
                    kind="operation_rule",
                    reading_mode="current_record",
                    read_at="execution",
                    required=True,
                    evidence_ids=["ev"],
                )
            )
        if revision == 101:
            package["relations.jsonl"].pop()
        repo.store_candidate(build["snapshot_id"], package)
        database.execute(
            f"update {table(database, 'code_snapshot')} set state='READY' where id=?",
            (build["snapshot_id"],),
        )
        snapshots.append(build["snapshot_id"])
    reader = CodeBehaviorReader(repo, lambda base, snapshot: "current-grant")
    root_id = knowledge_id(source_id, "factory.work_order.publish")
    first = reader.get(base_id, snapshots[0], root_id)
    assert first["has_more"] and first["partial"] and len(first["relations"]) == 50
    second = reader.get(base_id, snapshots[0], root_id, cursor=first["next_cursor"])
    assert not second["has_more"] and len(second["relations"]) == 5
    assert second["root"] == first["root"]
    assert len(reader.get(base_id, snapshots[1], root_id)["relations"]) == 50
    result = reader.compare(base_id, root_id, *snapshots)
    assert {"guard", "relations"} <= set(result["changed_fields"])
    assert result["changed_at_revision"] is None
    assert len(result["old_relations"]) == 55 and len(result["new_relations"]) == 54
    calls = []

    def revoked(base, snapshot):
        calls.append(1)
        return "allowed" if len(calls) == 1 else "revoked"

    with pytest.raises(CodeKnowledgeError, match="authorization_changed"):
        CodeBehaviorReader(repo, revoked).get(base_id, snapshots[0], root_id)


def test_upgrade_153_retains_ones_document_and_revision(tmp_path):
    import shutil
    from backend.tests.test_knowledge_import import prepare, export_row, run

    prior = tmp_path / "migrations"
    prior.mkdir()
    for path in default_migrations_dir().iterdir():
        if path.is_file() and not path.name.startswith("154_"):
            shutil.copyfile(path, prior / path.name)
    db = Database("sqlite:///:memory:")
    try:
        Migrator(db, prior, migrator_build="before-code").run()
        run(db, prepare(tmp_path, [export_row()]))
        before = db.execute(f"select * from {table(db, 'document')}")
        revisions = db.execute(f"select * from {table(db, 'document_revision')}")
        Migrator(db, default_migrations_dir(), migrator_build="after-code").run()
        assert before == db.execute(f"select * from {table(db, 'document')}")
        assert revisions == db.execute(f"select * from {table(db, 'document_revision')}")
        assert not db.execute("pragma foreign_key_check")
    finally:
        db.close()


def test_frozen_skill_content_survives_local_file_change(tmp_path):
    from app.modules.agent.infrastructure.skill_loader import SkillLoader

    name = "extract-business-knowledge"
    folder = tmp_path / name
    folder.mkdir()
    (folder / "SKILL.md").write_text("Original skill content")
    loader = SkillLoader(tmp_path)
    snapshot = {"skills": [name], "versioned_skills": loader.freeze_versioned((name,))}
    (folder / "SKILL.md").write_text("Changed after publication")
    assert loader.load_publication(snapshot)[name] == "Original skill content"
    assert loader.load((name,))[name] == "Changed after publication"
    snapshot["versioned_skills"][name]["content"] = "tampered"
    with pytest.raises(ValueError, match="digest"):
        loader.load_publication(snapshot)


def _assert_source_hook(extraction, active):
    # Native SDK reads inside cwd can bypass can_use_tool. The unconditional
    # hook must rewrite the virtual source path and recheck each operation.
    import asyncio
    from pathlib import Path
    from types import SimpleNamespace
    from app.modules.agent.domain.runtime import ToolCallBudget
    from app.python_runtime.mcp_config import _code_source_hook_options

    hooks = _code_source_hook_options(
        SimpleNamespace(hook_matcher=SimpleNamespace),
        extraction,
        SimpleNamespace(effective_tool_names=("Read", "Write")),
        ToolCallBudget(maximum=3),
    )
    hook = hooks["hooks"]["PreToolUse"][0].hooks[0]
    hook_event = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(extraction.path / "source/set_server/order.cpp")},
    }
    admitted = asyncio.run(hook(hook_event, "read-1", None))["hookSpecificOutput"]
    assert admitted["permissionDecision"] == "allow"
    assert Path(admitted["updatedInput"]["file_path"]).read_text().endswith("return accepted;\n")
    denied = asyncio.run(
        hook({"tool_name": "Bash", "tool_input": {"command": "pwd"}}, "shell", None)
    )
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    active[0] = False
    revoked = asyncio.run(hook(hook_event, "read-2", None))["hookSpecificOutput"]
    assert revoked["permissionDecision"] == "deny" and "updatedInput" not in revoked
    active[0] = True


def test_runtime_source_mount_is_snapshot_bound_and_read_only(tmp_path):
    from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector
    from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory
    from app.python_runtime.code_source_mount import CodeSourceMount
    from app.python_runtime.job_sandbox import JobSandboxManager, JobSandboxError

    root = tmp_path.resolve() / "source"
    for component in ("set_server", "set_web/EBR", "set_web/JTH"):
        (root / component).mkdir(parents=True)
    (root / "set_server/order.cpp").write_bytes("// 工单\r\nreturn accepted;\r\n".encode("gb18030"))
    (root / "set_server/long.cpp").write_text("x" * 2000 + "\n")
    (root / "set_web/EBR/order.vue").write_text("factory")
    (root / "set_web/JTH/app.js").write_text("group")
    collector = LocalCodeCollector(root)
    frozen = collector.freeze()
    store = CodeSnapshotDirectory(tmp_path.resolve() / "snapshots")
    published = store.publish("snapshot-100", frozen, collector)
    assert store.publish("snapshot-100", frozen, collector) == published
    assert (published / "raw/set_server/order.cpp").read_bytes() == (
        root / "set_server/order.cpp"
    ).read_bytes()
    active = [True]

    def recheck():
        if not active[0]:
            raise CodeKnowledgeError("code_source_authorization_revoked")

    mounted = CodeSourceMount(
        root=store.root,
        snapshot_id="snapshot-100",
        manifest_hash=frozen.source_ref["manifest_hash"],
        allowed_prefixes=("set_server",),
        recheck=recheck,
    )
    manager = JobSandboxManager(tmp_path.resolve() / "sandboxes")
    extraction = manager.create("extraction")
    ordinary = manager.create("ordinary")
    try:
        extraction.source_mount = mounted
        read = extraction.authorize_tool("Read", {"file_path": "source/set_server/order.cpp"})
        assert read["limit"] == 400 and read["file_path"] == str(
            published / "text/set_server/order.cpp"
        )
        assert (
            extraction.authorize_tool(
                "Read", {"file_path": str(extraction.path / "source/set_server/order.cpp")}
            )
            == read
        )
        _assert_source_hook(extraction, active)
        sidecar = extraction.authorize_tool(
            "Read", {"file_path": "source/set_server/order.cpp.evidence.txt"}
        )
        assert str(sidecar["file_path"]).endswith("order.cpp.evidence.txt")
        assert (
            extraction.authorize_tool("Grep", {"path": "source/set_server", "pattern": "accepted"})[
                "head_limit"
            ]
            == 100
        )
        content_search = extraction.authorize_tool(
            "Grep",
            {
                "path": "source/set_server/order.cpp",
                "pattern": "accepted",
                "output_mode": "content",
            },
        )
        assert content_search["-n"] is True and content_search["head_limit"] == 40
        with pytest.raises(JobSandboxError):
            extraction.authorize_tool(
                "Grep", {"path": "source/set_server", "pattern": ".*", "output_mode": "content"}
            )
        for tool, arguments in (
            (
                "Grep",
                {"path": "source/set_server/long.cpp", "pattern": ".*", "output_mode": "content"},
            ),
            ("Write", {"file_path": "source/set_server/order.cpp", "content": "modified"}),
            ("Write", {"file_path": "work/candidate.txt", "content": "modified"}),
            ("Read", {"file_path": "source/set_web/JTH/app.js"}),
            ("Read", {"file_path": "source/set_server/../../secret"}),
            ("Read", {"file_path": str(store.root / "snapshot-101/text/set_server/order.cpp")}),
        ):
            with pytest.raises(JobSandboxError):
                extraction.authorize_tool(tool, arguments)
        with pytest.raises(JobSandboxError):
            ordinary.authorize_tool("Read", {"file_path": read["file_path"]})
        active[0] = False
        with pytest.raises(JobSandboxError):
            extraction.authorize_tool("Read", {"file_path": "source/set_server/order.cpp"})
    finally:
        extraction.cleanup()
        ordinary.cleanup()
        # This test owns these directories; restore permissions only for fixture cleanup.
        for path in [published, *published.rglob("*")]:
            path.chmod(0o750 if path.is_dir() else 0o640)


def test_runtime_collects_only_exact_invocation_artifacts(tmp_path):
    from app.modules.knowledge.infrastructure.code_artifact_directory import CodeArtifactDirectory

    package, _ = fixture()
    binding = dict(
        job_id="job",
        invocation_id="job.attempt-0",
        request_digest="a" * 64,
        grant={"candidate_manifest": deepcopy(package["manifest.json"])},
    )
    sandbox = tmp_path.resolve() / "sandbox"
    outputs = sandbox / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "candidate.txt").write_bytes(encode_package(package))
    (outputs / "report.md").write_text("Synthetic report")
    artifacts = CodeArtifactDirectory(tmp_path.resolve() / "artifacts")
    manifest = artifacts.publish(sandbox, binding)
    assert artifacts.publish(sandbox, binding) == manifest
    (outputs / "candidate.txt").unlink()
    assert decode_package(artifacts.read(binding)[1]["candidate.txt"]) == package
    with pytest.raises((OSError, CodeKnowledgeError)):
        artifacts.read({**binding, "invocation_id": "job.attempt-1"})
    (outputs / "candidate.txt").write_bytes(encode_package(package))
    (outputs / "report.md").write_text("Different late result")
    with pytest.raises(CodeKnowledgeError, match="artifact_conflict"):
        artifacts.publish(sandbox, binding)
    package["manifest.json"]["build_id"] = "other-build"
    (outputs / "candidate.txt").write_bytes(encode_package(package))
    with pytest.raises(CodeKnowledgeError, match="binding_mismatch"):
        artifacts.publish(sandbox, binding)


def test_code_runtime_service_identity_cannot_use_other_audiences():
    import time
    from app.modules.identity.application.service_principal import (
        ServicePrincipalTokenIssuer,
        CodeRuntimeServicePrincipalVerifier,
        KnowledgeServicePrincipalVerifier,
        ServicePrincipalTokenError,
    )
    from app.modules.identity.application.principal_jwt import PrincipalJwks
    from backend.tests.test_service_principal_identity import _issuer

    base, audit = _issuer(now=int(time.time()))
    issuer = ServicePrincipalTokenIssuer(
        signing_key=base.signing_key,
        audit_service=audit,
        bootstrap_credentials={**base._bootstrap_credentials, "code-knowledge-runtime": "c" * 48},
    )
    keys = PrincipalJwks.from_dict(base.signing_key.public_jwks())
    token = issuer.issue("c" * 48).access_token
    CodeRuntimeServicePrincipalVerifier(keys).verify(token)
    with pytest.raises(ServicePrincipalTokenError):
        KnowledgeServicePrincipalVerifier(keys).verify(token)
    with pytest.raises(ServicePrincipalTokenError):
        CodeRuntimeServicePrincipalVerifier(keys).verify(base.issue("f" * 48).access_token)


def _freeze_test_source(tmp_path, repo, source_id):
    from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector
    from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory

    root = tmp_path.resolve() / "code"
    for component in ("set_server", "set_web/EBR", "set_web/JTH"):
        (root / component).mkdir(parents=True)
    (root / "set_server/work_order.cpp").write_text(fixture()[1]["file"].text)
    collector = LocalCodeCollector(root)
    frozen = collector.freeze()
    identifier = repo.freeze_source(source_id, frozen.source_ref, frozen.manifest)
    directory = CodeSnapshotDirectory(tmp_path.resolve() / "snapshots")
    directory.publish(identifier, frozen, collector)
    return identifier, directory.root


@pytest.fixture
def code_job_runtime(tmp_path):
    import json
    from app.modules.agent.infrastructure.skill_loader import SkillLoader
    from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
    from app.modules.knowledge.infrastructure.storage import insert
    from app.modules.knowledge.domain.identity import now
    from backend.tests.support.runtime import container
    from backend.tests.support.applications import activate_dingtalk_test_application
    from backend.tests.support.authorization import grant_test_application_access

    runtime = container()
    db = runtime.database
    try:
        pub_id = "agent_publication_default_v1"
        pub = db.execute_one("select * from agent_publication where id=?", (pub_id,))
        snapshot = json.loads(pub["snapshot_json"])
        snapshot["skills"] = ["extract-business-knowledge"]
        snapshot["versioned_skills"] = SkillLoader().freeze_versioned(tuple(snapshot["skills"]))
        db.execute(
            "update agent_publication set snapshot_json=?,config_hash=? where id=?",
            (json.dumps(snapshot), digest(snapshot), pub_id),
        )
        app_pub = activate_dingtalk_test_application(
            runtime,
            code="extract-test",
            robot_code="extract-test-bot",
            capabilities=(),
        )
        application = runtime.business_application_repository.get_by_code("extract-test")
        svc = runtime.identity_repository.create_user(
            username="code-test-service", display_name="Code Test", account_type="service"
        )
        role = grant_test_application_access(
            runtime,
            application_id=application["id"],
            role_code="extract-test-role",
            user_id=svc["id"],
        )
        pub = db.execute_one("select * from agent_publication where id=?", (pub_id,))
        config = dict(
            service_account_id=svc["id"],
            agent_publication_id=pub_id,
            agent_config_hash=pub["config_hash"],
            application_id=application["id"],
            application_publication_id=app_pub["id"],
            application_config_hash=app_pub["config_hash"],
        )
        repo = CodeRepository(db)
        source = repo.register(code="code-internal", base_code="code-base", config={})["source_id"]
        source_id, source_root = _freeze_test_source(tmp_path, repo, source)
        build = repo.new_build(source, source_id, purpose="baseline", configuration=config)
        builds = CodeBuildRepository(db)
        lease = builds.claim(build["build_id"])
        builds.advance(build["build_id"], lease, "QUEUED")
        builds.advance(build["build_id"], lease, "SOURCE_READY")
        insert(
            db,
            "code_unit",
            dict(
                id="code-unit-test",
                build_id=build["build_id"],
                unit_key="publish",
                scope_json={"allowed_prefixes": ["set_server"], "entry_ids": ["publish"]},
                state="QUEUED",
                created_at=now(),
                updated_at=now(),
            ),
        )
        yield runtime, svc, role, pub, app_pub, application, source_id, lease, source_root
    finally:
        db.close()


def test_internal_code_job_binding_outbox_and_live_revocation(code_job_runtime):
    import json
    from pathlib import Path
    from datetime import UTC, datetime, timedelta
    from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore
    from app.modules.agent.infrastructure.runtime_protocol import canonical_request_digest
    from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
    from app.modules.knowledge.infrastructure.code_source_grant import CodeSourceGrant
    from app.shared.exceptions import PermissionDenied

    runtime, svc, role, pub, app_pub, application, source_id, lease, _ = code_job_runtime
    db = runtime.database
    pub_id = pub["id"]
    command = CreateAgentJobCommand(
        idempotency_key="code-unit:code-unit-test",
        user_message="Extract synthetic business rules",
        requester_id=svc["id"],
        source_channel="code_knowledge",
        source_connector_id="internal-code-knowledge",
        reply_route={"type": "none"},
        agent_code=runtime.settings.identity.default_agent_code,
        fixed_agent_publication_id=pub_id,
        fixed_agent_config_hash=pub["config_hash"],
        business_application_id=application["id"],
        business_application_code="extract-test",
        business_application_publication_id=app_pub["id"],
        business_application_config_hash=app_pub["config_hash"],
        conversation_mode="channel",
    )
    with pytest.raises(PermissionDenied):
        runtime.create_agent_job_service.execute(command)
    job = runtime.create_agent_job_service.execute_code_unit(
        command, unit_id="code-unit-test", lease_version=lease
    )
    replay = runtime.create_agent_job_service.execute_code_unit(
        command, unit_id="code-unit-test", lease_version=lease
    )
    assert replay.id == job.id
    assert job.reply_route["type"] == "none"
    assert (
        db.execute_one("select count(*) as n from job_dispatch_outbox where job_id=?", (job.id,))[
            "n"
        ]
        == 1
    )
    assert not job.task_workspace_id
    db.execute("update agent_job set status='RUNNING' where id=?", (job.id,))
    grants = CodeSourceGrant(db, runtime.business_authorization_service)
    grant = grants.for_job(job.id)
    assert grant["candidate_manifest"]["source_snapshot_id"] == source_id
    request = json.loads(
        Path("contracts/agent-runtime/v1.5/golden/execution-request.json").read_text()
    )
    request.update(
        job_id=job.id,
        invocation_id=job.id + ".attempt-0",
        mcp_servers=[],
        app_user_id=svc["id"],
        agent_publication_id=pub_id,
        application_publication_id=app_pub["id"],
    )
    request["request_digest"] = canonical_request_digest(request)
    pool = RuntimePoolStore(db)
    pool.prepare(
        request,
        attempt=0,
        admission_deadline_at=(datetime.now(UTC) + timedelta(seconds=300)).isoformat(),
    )
    pool.admit(request["invocation_id"], request["request_digest"], "a", "test-instance")
    identity = {key: request[key] for key in ("job_id", "invocation_id", "request_digest")}
    assert grants.check_invocation(identity) == grant
    with pytest.raises(CodeKnowledgeError):
        grants.check_invocation({**identity, "request_digest": "f" * 64})
    runtime.identity_repository.remove_role(
        user_id=svc["id"], role_id=role["id"], expected_revision=1
    )
    with pytest.raises(PermissionDenied):
        grants.check_invocation(identity)


def test_runtime_mount_authoring_sealing_and_cleanup_lifecycle(tmp_path):
    import asyncio
    from app.modules.agent.domain.runtime import (
        AgentExecutionContext,
        AgentRunRequest,
        AgentRunResult,
    )
    from app.modules.knowledge.domain.normalization import canonical_json
    from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector
    from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory
    from app.python_runtime.claude_client import ClaudeSdkClient
    from app.python_runtime.code_extraction import CodeExtractionSandboxes
    from app.python_runtime.job_sandbox import JobSandboxManager
    from app.shared.config import ExecutionSettings

    package, evidence = fixture(source_snapshot_id="runtime-snapshot")
    root = tmp_path.resolve() / "source"
    for component in ("set_server", "set_web/EBR", "set_web/JTH"):
        (root / component).mkdir(parents=True)
    (root / "set_server/work_order.cpp").write_text(evidence["file"].text)
    collector = LocalCodeCollector(root)
    frozen = collector.freeze()
    snapshots = CodeSnapshotDirectory(tmp_path.resolve() / "snapshots")
    snapshots.publish("runtime-snapshot", frozen, collector)
    package["evidence.jsonl"][0]["file_id"] = frozen.manifest["files"][0]["file_id"]
    package["manifest.json"]["source_ref"] = frozen.source_ref
    grant = dict(
        candidate_manifest=package["manifest.json"],
        manifest_hash=frozen.source_ref["manifest_hash"],
        allowed_prefixes=["set_server"],
        scope={"entry_ids": [row["entry_id"] for row in package["coverage.json"]["entries"]]},
    )
    authoring = {"contract_version": CONTRACT_VERSION, "entries": deepcopy(package)}
    authoring["entries"]["evidence.jsonl"][0]["excerpt_hash"] = None

    class Grants:
        def check(self, _):
            return deepcopy(grant)

    request = dict(
        job_id="job",
        invocation_id="job.attempt-0",
        request_digest="a" * 64,
        mcp_servers=[],
        prompt={
            "retrieved_context": {"code_source": grant},
            "skills": {"extract-business-knowledge": "test"},
        },
    )
    manager = CodeExtractionSandboxes(
        JobSandboxManager(tmp_path.resolve() / "sandboxes"),
        request,
        source_root=snapshots.root,
        artifact_root=tmp_path.resolve() / "artifacts",
        grants=Grants(),
    )
    paths = []

    class SyntheticClient(ClaudeSdkClient):
        fail = False

        async def _run_in_sandbox_async(self, *_):
            from types import SimpleNamespace
            from app.modules.agent.domain.runtime import ToolCallBudget
            from app.python_runtime.mcp_config import _code_source_hook_options

            sandbox = self._sandbox.get()
            paths.append(sandbox.path)
            assert (sandbox.path / "inputs/code-contract.txt").is_file()
            contract = json.loads((sandbox.path / "inputs/code-contract.txt").read_text())
            assert contract["source_access"]["read_root"] == str(sandbox.source_mount.root)
            assert (
                sandbox.authorize_tool(
                    "Grep",
                    {
                        "path": contract["source_access"]["read_root"]
                        + "/set_server/work_order.cpp",
                        "pattern": "accepted",
                        "output_mode": "content",
                    },
                )["head_limit"]
                == 40
            )
            sandbox.authorize_tool("Read", {"file_path": "source/set_server/work_order.cpp"})
            hooks = _code_source_hook_options(
                SimpleNamespace(hook_matcher=SimpleNamespace),
                sandbox,
                SimpleNamespace(
                    effective_tool_names=("Write", "Edit"), retrieved_context={"code_source": grant}
                ),
                ToolCallBudget(maximum=5),
            )
            hook = hooks["hooks"]["PreToolUse"][0].hooks[0]
            duplicate = deepcopy(authoring)
            duplicate["entries"]["coverage.json"]["entries"] *= 2
            for obj, allowed in ((duplicate, False), (authoring, True)):
                decision = (
                    await hook(
                        {
                            "tool_name": "Write",
                            "tool_input": {
                                "file_path": "outputs/candidate.txt",
                                "content": canonical_json(obj),
                            },
                        },
                        "candidate-write",
                        None,
                    )
                )["hookSpecificOutput"]
                assert (decision["permissionDecision"] == "allow") == allowed
                if not allowed:
                    assert "code_duplicate_identity" in decision["permissionDecisionReason"]
            (sandbox.path / "outputs/candidate.txt").write_text(canonical_json(authoring))
            (sandbox.path / "outputs/report.md").write_text("Synthetic report")
            if self.fail:
                raise ValueError("synthetic interruption")
            return AgentRunResult("done")

    context = AgentExecutionContext(
        "test", [], "extract", "default", [], [], {}, {"code_source": grant}, ""
    )
    client = SyntheticClient(
        model="", api_key="", limits=ExecutionSettings(), sandbox_manager=manager
    )
    run_request = AgentRunRequest("job", "service", "default", context)
    asyncio.run(client._run_async(run_request, None, ""))
    binding = {**manager.identity, "grant": grant}
    assert decode_package(manager.artifacts.read(binding)[1]["candidate.txt"]) == package
    assert not paths[-1].exists()
    manager.identity["invocation_id"] = "job.attempt-1"
    client.fail = True
    with pytest.raises(ValueError):
        asyncio.run(client._run_async(run_request, None, ""))
    assert not paths[-1].exists()
    assert not (
        manager.artifacts.root / manager.artifacts.key({**manager.identity, "grant": grant})
    ).exists()


def test_extraction_audit_retains_usage_without_source_bodies(tmp_path):
    import json
    from app.modules.agent.domain.runtime import AgentExecutionContext
    from app.python_runtime.run_audit import RunAuditRecorder

    context = AgentExecutionContext(
        "test", [], "extract", "default", [], [], {}, {"code_source": {"job_id": "synthetic"}}, ""
    )
    audit = RunAuditRecorder(
        context, system_prompt="test", raw_api_dir=tmp_path, permission_snapshot={}
    )
    audit.observe_message(
        {
            "type": "assistant",
            "content": [{"type": "text", "text": "SYNTHETIC_SOURCE_BODY"}],
            "usage": {"input_tokens": 12},
        }
    )
    result = audit.finalize(status="SUCCEEDED")
    assert "SYNTHETIC_SOURCE_BODY" not in json.dumps(result)
    assert result["model_requests"][0]["usage"]["input_tokens"] == 12
    assert not result["sdk_messages"] and not result["api_requests"]


def test_runtime_code_grant_endpoint_is_metadata_only_and_not_a_browser_route():
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.modules.knowledge.api.code_runtime_controller import build_code_runtime_router
    from app.modules.knowledge.domain.code_contracts import CODE_SOURCE_GRANT_PATH

    class Verifier:
        def verify(self, token):
            if token != "synthetic-runtime-token":
                raise ValueError

    class Grant:
        def check_invocation(self, value):
            assert value == {"job_id": "job", "invocation_id": "inv", "request_digest": "a" * 64}
            return {"source_snapshot_id": "snapshot", "allowed_prefixes": ["set_server"]}

    app = FastAPI()
    app.state.container = SimpleNamespace(
        code_runtime_verifier=Verifier(), code_source_grant=Grant()
    )
    app.include_router(build_code_runtime_router())
    payload = {"job_id": "job", "invocation_id": "inv", "request_digest": "a" * 64}
    headers = {"Authorization": "Bearer synthetic-runtime-token"}
    with TestClient(app, base_url="http://api-server:8000") as client:
        response = client.post(CODE_SOURCE_GRANT_PATH, json=payload, headers=headers)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert client.post(CODE_SOURCE_GRANT_PATH, json=payload).status_code == 403
        for field, value in (
            ("Origin", "http://example.test"),
            ("Cookie", "synthetic=1"),
            ("Host", "example.test"),
        ):
            assert (
                client.post(
                    CODE_SOURCE_GRANT_PATH, json=payload, headers={**headers, field: value}
                ).status_code
                == 403
            )
        assert (
            client.post(
                CODE_SOURCE_GRANT_PATH,
                content="x" * 1025,
                headers={**headers, "Content-Type": "application/json"},
            ).status_code
            == 403
        )


def test_local_baseline_registration_is_idempotent_and_capacity_is_bounded(database, tmp_path):
    from app.modules.knowledge.infrastructure.code_baseline import CodeBaselineAdmission
    from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector
    from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory

    root = tmp_path.resolve() / "source"
    for component in ("set_server", "set_web/EBR", "set_web/JTH"):
        (root / component).mkdir(parents=True)
    (root / "set_server/order.cpp").write_text("return accepted;\n")
    collector = LocalCodeCollector(root)
    frozen = collector.freeze()
    admission = CodeBaselineAdmission(database, tmp_path.resolve() / "snapshots")
    first = admission.admit(
        collector, frozen, source_code="local", base_code="local-code", local_root_key="mes-current"
    )
    second = admission.admit(
        collector, frozen, source_code="local", base_code="local-code", local_root_key="mes-current"
    )
    assert first == second and first["svn_revision"] is None
    assert (
        database.execute_one(f"select count(*) as n from {table(database, 'code_source_file')}")[
            "n"
        ]
        == 1
    )
    with pytest.raises(CodeKnowledgeError, match="capacity_exceeded"):
        CodeSnapshotDirectory(tmp_path.resolve() / "tiny", max_bytes=10).publish(
            "snapshot", frozen, collector
        )
    (root / "set_server/new.cpp").write_text("return unknown;\n")
    with pytest.raises(CodeKnowledgeError, match="source_changed"):
        admission.directory.publish("different-snapshot", frozen, collector)


def test_runtime_docker_whitelist_imports_without_control_plane(tmp_path):
    import os
    from pathlib import Path
    import shutil
    import subprocess
    import sys

    dockerfile = Path("backend/Dockerfile").read_text()
    stage = dockerfile.split("FROM claude-runtime AS python-agent-runtime", 1)[1].split(
        "\nFROM ", 1
    )[0]
    for line in stage.splitlines():
        if not line.startswith("COPY backend/app/"):
            continue
        *patterns, destination = line.split()[1:]
        target = tmp_path / destination.removeprefix("/app/")
        target.mkdir(parents=True, exist_ok=True)
        for pattern in patterns:
            for source in Path().glob(pattern):
                if source.is_dir():
                    shutil.copytree(source, target, dirs_exist_ok=True)
                else:
                    shutil.copyfile(source, target / source.name)
    # -I and an isolated cwd prevent importing omitted modules from this checkout.
    code = "import sys; sys.path.insert(0, sys.argv[1]); import app.python_runtime.service; assert 'app.bootstrap' not in sys.modules; assert 'app.modules.identity.application.principal_jwt' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(tmp_path / "backend")],
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("takeover", [False, True])
@pytest.mark.parametrize("import_failure", [False, True])
def test_dispatch_and_artifact_import_require_successful_exact_invocation(
    code_job_runtime, tmp_path, takeover, import_failure, monkeypatch
):
    from pathlib import Path
    from datetime import UTC, datetime, timedelta
    from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore
    from app.modules.agent.infrastructure.runtime_protocol import canonical_request_digest
    from app.modules.knowledge.infrastructure.code_extraction_jobs import (
        CodeExtractionJobs,
        CodeArtifactCollector,
    )
    from app.modules.knowledge.infrastructure.code_source_grant import CodeSourceGrant
    from app.modules.knowledge.infrastructure.code_artifact_directory import CodeArtifactDirectory

    runtime, svc, _, pub, app_pub, _, source_id, lease, source_root = code_job_runtime
    db = runtime.database
    dispatcher = CodeExtractionJobs(db, runtime.create_agent_job_service)
    job = dispatcher.dispatch("code-unit-test", lease)
    assert dispatcher.dispatch("code-unit-test", lease).id == job.id
    db.execute("update agent_job set status='RUNNING' where id=?", (job.id,))
    grants = CodeSourceGrant(db, runtime.business_authorization_service)
    grant = grants.for_job(job.id)
    request = json.loads(
        Path("contracts/agent-runtime/v1.5/golden/execution-request.json").read_text()
    )
    request.update(
        job_id=job.id,
        invocation_id=job.id + ".attempt-0",
        mcp_servers=[],
        app_user_id=svc["id"],
        agent_publication_id=pub["id"],
        application_publication_id=app_pub["id"],
    )
    request["prompt"]["retrieved_context"] = {"code_source": grant}
    request["request_digest"] = canonical_request_digest(request)
    pool = RuntimePoolStore(db)
    pool.prepare(
        request,
        attempt=0,
        admission_deadline_at=(datetime.now(UTC) + timedelta(seconds=300)).isoformat(),
    )
    pool.admit(request["invocation_id"], request["request_digest"], "a", "test-instance")
    binding = {key: request[key] for key in ("job_id", "invocation_id", "request_digest")} | {
        "grant": grant
    }
    package, _ = fixture(source_snapshot_id=source_id)
    package["manifest.json"] = grant["candidate_manifest"]
    manifest = json.loads((source_root / source_id / "manifest.json").read_text())
    package["evidence.jsonl"][0]["file_id"] = manifest["files"][0]["file_id"]
    outputs = tmp_path / "sandbox/outputs"
    outputs.mkdir(parents=True)
    (outputs / "candidate.txt").write_bytes(encode_package(package))
    (outputs / "report.md").write_text("Synthetic independent candidate")
    artifacts = CodeArtifactDirectory(tmp_path.resolve() / "artifacts")
    artifacts.publish(outputs.parent, binding)
    collector = CodeArtifactCollector(
        db, grants, source_root=source_root, artifact_root=artifacts.root
    )
    with pytest.raises(CodeKnowledgeError, match="job_inactive"):
        collector.collect("code-unit-test", lease)
    db.execute("update agent_job set status='SUCCEEDED' where id=?", (job.id,))
    with pytest.raises(CodeKnowledgeError, match="terminal_unproven"):
        collector.collect("code-unit-test", lease)
    _complete_invocation(db, pool, request)
    if takeover:
        lease = _take_over_build(db, grant)
        assert grants.for_job(job.id, completed=True) == grant
    if import_failure:
        _assert_candidate_commit_rollback(db, collector, lease, monkeypatch)
    _assert_candidate_import_idempotent(db, collector, lease)
    _assert_controller_review(db, dispatcher, collector, source_root, grant, lease)
    assert (
        db.execute_one("select count(*) as n from agent_job where source_channel='code_knowledge'")[
            "n"
        ]
        == 1
    )


def _assert_candidate_import_idempotent(db, collector, lease):
    result = collector.collect("code-unit-test", lease)
    assert result["machine_valid"] and not result["business_verified"]
    assert collector.collect("code-unit-test", lease) == result
    assert db.execute_one(f"select count(*) as n from {table(db, 'code_member')}")["n"] == 1
    assert (
        db.execute_one(f"select state from {table(db, 'code_unit')} where id='code-unit-test'")[
            "state"
        ]
        == "VALIDATED"
    )


def _assert_candidate_commit_rollback(db, collector, lease, monkeypatch):
    store = CodeRepository.store_candidate

    def failed_commit(repository, snapshot_id, candidate):
        store(repository, snapshot_id, candidate)
        raise RuntimeError("synthetic failure after candidate writes")

    with monkeypatch.context() as patch:
        patch.setattr(CodeRepository, "store_candidate", failed_commit)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            collector.collect("code-unit-test", lease)
    assert db.execute_one(f"select count(*) as n from {table(db, 'code_member')}")["n"] == 0
    assert db.execute_one(f"select state from {table(db, 'code_unit')}")["state"] != "VALIDATED"


def _take_over_build(db, grant):
    from datetime import UTC, datetime, timedelta
    from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository

    build_id = grant["candidate_manifest"]["build_id"]
    db.execute(
        f"update {table(db, 'code_build')} set lease_until=? where id=?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), build_id),
    )
    lease = CodeBuildRepository(db).claim(build_id)
    assert lease == grant["lease_version"] + 1
    return lease


def _complete_invocation(db, pool, request):
    pool.quiesce(request["invocation_id"], "a", "test-instance")
    with db.unit_of_work():
        pool.finish(
            request["invocation_id"],
            request["request_digest"],
            "a",
            "test-instance",
            "runtime_succeeded",
        )


def _assert_controller_review(db, dispatcher, collector, source_root, grant, lease):
    from app.modules.knowledge.infrastructure.code_build_controller import CodeBuildController

    controller = CodeBuildController(db, dispatcher, collector, source_root=source_root)
    build_id = grant["candidate_manifest"]["build_id"]
    controller.leases[build_id] = lease
    assert controller.step(build_id)["state"] == "VALIDATING"
    assert controller.step(build_id)["state"] == "BUSINESS_REVIEW_REQUIRED"


def test_scope_locator_is_navigation_not_inferred_business_rules():
    from app.modules.knowledge.infrastructure.code_scope import locate

    path = "set_server/src/order.cpp"
    text = '#include "order.h"\n#include "unknown.h"\n#ifdef ENABLE_CHECK\nvoid Order::Publish() {\n if (state == 1) return;\n}\n#endif\n'
    result = locate(path, text, {path, "set_server/include/order.h"})
    assert {row["symbol"] for row in result["locations"] if "symbol" in row} == {"Order::Publish"}
    assert result["references"][0]["candidate_paths"] == ["set_server/include/order.h"]
    assert result["references"][1]["resolution"] == "unresolved"
    assert {row["code"] for row in result["unknowns"]} == {
        "reference_requires_analysis",
        "conditional_compilation_requires_analysis",
    }
    assert set(result) == {"locations", "references", "unknowns"}


def test_source_retirement_keeps_knowledge_and_requires_new_admission(database, tmp_path):
    from datetime import UTC, datetime, timedelta
    from app.modules.knowledge.infrastructure.code_retention import CodeSourceRetention
    from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector
    from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory

    repo = CodeRepository(database)
    ids = repo.register(code="retention", base_code="retention-base", config={})
    source, root = _freeze_test_source(tmp_path, repo, ids["source_id"])
    retirement = CodeSourceRetention(database, root)
    with pytest.raises(CodeKnowledgeError, match="not_due"):
        retirement.retire(source, commit=True)
    database.execute(
        f"update {table(database, 'code_source_snapshot')} set created_at=? where id=?",
        ((datetime.now(UTC) - timedelta(days=31)).isoformat(), source),
    )
    build = repo.new_build(ids["source_id"], source, purpose="baseline", configuration={})
    with pytest.raises(CodeKnowledgeError, match="in_use"):
        retirement.retire(source, commit=True)
    package, _ = fixture(source_snapshot_id=source)
    repo.store_candidate(build["snapshot_id"], package)
    database.execute(
        f"update {table(database, 'code_build')} set stage='READY' where id=?", (build["build_id"],)
    )
    database.execute(
        f"update {table(database, 'code_snapshot')} set state='READY' where id=?",
        (build["snapshot_id"],),
    )
    assert retirement.retire(source)["state"] == "ELIGIBLE"
    assert (root / source).is_dir()
    assert retirement.retire(source, commit=True)["state"] == "RETIRED"
    assert not (root / source).exists()
    assert retirement.retire(source, commit=True)["state"] == "RETIRED"
    member = repo.read_member(
        ids["knowledge_base_id"],
        build["snapshot_id"],
        knowledge_id(ids["source_id"], "factory.work_order.publish"),
    )
    assert member["knowledge"]["guard"]["expression"] == "a is not empty"
    assert member["source_evidence_status"] == "retired"
    with pytest.raises(CodeKnowledgeError, match="source_retired"):
        repo.new_build(ids["source_id"], source, purpose="history", configuration={})
    collector = LocalCodeCollector(tmp_path.resolve() / "code")
    frozen = collector.freeze()
    new_source = repo.freeze_source(ids["source_id"], frozen.source_ref, frozen.manifest)
    assert new_source != source
    assert repo.freeze_source(ids["source_id"], frozen.source_ref, frozen.manifest) == new_source
    CodeSnapshotDirectory(root).publish(new_source, frozen, collector)
    assert (root / new_source).is_dir() and not (root / source).exists()


def test_scope_planner_persists_idempotent_bounded_units(database, tmp_path):
    from app.modules.knowledge.infrastructure.code_scope import CodeScopePlanner, ENTRY_STARTS
    from app.modules.knowledge.infrastructure.code_source import LocalCodeCollector
    from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory

    repo = CodeRepository(database)
    ids = repo.register(code="scope", base_code="scope-base", config={})
    code = tmp_path.resolve() / "code"
    for path in {p for paths in ENTRY_STARTS.values() for p in paths}:
        target = code / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("// status hint\n" * 250 + "void Logic::CheckState() {\n return;\n}\n")
    collector = LocalCodeCollector(code)
    frozen = collector.freeze()
    source = repo.freeze_source(ids["source_id"], frozen.source_ref, frozen.manifest)
    root = tmp_path.resolve() / "sources"
    CodeSnapshotDirectory(root).publish(source, frozen, collector)
    build = repo.new_build(ids["source_id"], source, purpose="baseline", configuration={})
    planner = CodeScopePlanner(root)
    assert planner.persist(database, build["build_id"]) == 6
    assert planner.persist(database, build["build_id"]) == 6
    rows = database.execute(
        f"select scope_json from {table(database, 'code_unit')} where build_id=?",
        (build["build_id"],),
    )
    assert len(rows) == 6
    assert all(json.loads(r["scope_json"])["locations"] for r in rows)
    assert all(
        json.loads(r["scope_json"])["locations"][0]["symbol"] == "Logic::CheckState" for r in rows
    )
    assert all(not json.loads(r["scope_json"])["locator_unknowns"] for r in rows)
    assert not database.execute(f"select id from {table(database, 'document')}")


def test_svn_child_output_is_bounded_and_reaped(tmp_path):
    import subprocess
    import sys
    from app.modules.knowledge.infrastructure.code_svn import _bounded_output

    with subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x'*8192)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        try:
            with pytest.raises(CodeKnowledgeError, match="too_large"):
                _bounded_output(process, timeout=2, limit=1024)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def test_dependency_expansion_uses_only_admitted_approved_paths(database, tmp_path):
    from app.modules.knowledge.infrastructure.code_dependency_expansion import expand_dependencies
    from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
    from app.modules.knowledge.infrastructure.storage import insert
    from app.modules.knowledge.domain.identity import now

    repo = CodeRepository(database)
    source_id = repo.register(
        code="expand", base_code="expand-base", config={"approved_dependency_roots": ["set_server"]}
    )["source_id"]
    source, _ = _freeze_test_source(tmp_path, repo, source_id)
    build = repo.new_build(source_id, source, purpose="baseline", configuration={})
    builds = CodeBuildRepository(database)
    lease = builds.claim(build["build_id"])
    for stage in ("QUEUED", "SOURCE_READY"):
        builds.advance(build["build_id"], lease, stage)
    request = {
        "entry_id": "publish",
        "path": "set_server/work_order.cpp",
        "reason": "Referenced implementation outside this unit",
    }
    insert(
        database,
        "code_unit",
        dict(
            id="expand-unit",
            build_id=build["build_id"],
            unit_key="publish",
            state="VALIDATED",
            scope_json={"entry_ids": ["publish"], "allowed_prefixes": ["set_server/include"]},
            result_json={"dependency_requests": [request]},
            created_at=now(),
            updated_at=now(),
        ),
    )
    unit = database.execute_one(
        f"select * from {table(database, 'code_unit')} where id='expand-unit'"
    )
    denied = {
        **unit,
        "result_json": {
            "dependency_requests": [{**request, "path": "set_web/EBR_SPLIT/private.vue"}]
        },
    }
    with pytest.raises(CodeKnowledgeError, match="expansion_denied"):
        expand_dependencies(database, denied, lease)
    child_id = expand_dependencies(database, unit, lease)
    assert expand_dependencies(database, unit, lease) == child_id
    child = database.execute_one(
        f"select * from {table(database, 'code_unit')} where id=?", (child_id,)
    )
    scope = json.loads(child["scope_json"])
    assert scope["allowed_prefixes"] == ["set_server/include", "set_server/work_order.cpp"]
    assert scope["expansion_depth"] == 1 and child["job_id"] is None
    assert (
        database.execute_one(f"select count(*) as n from {table(database, 'code_unit')}")["n"] == 2
    )
    with pytest.raises(CodeKnowledgeError, match="budget_exhausted"):
        expand_dependencies(
            database, {**unit, "scope_json": {**scope, "expansion_depth": 2}}, lease
        )
