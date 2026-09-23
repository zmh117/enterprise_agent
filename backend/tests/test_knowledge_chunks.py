from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.import_repository import ImportRepository
from copy import deepcopy
from dataclasses import replace
import json
import os
import random
import uuid

import pytest

from app.cli.prepare_knowledge_chunks import main
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.domain.chunking import (
    DEFAULT_PROFILE,
    clean_text,
    prepare_chunks,
    validate_chunks,
)
from app.modules.knowledge.application.import_service import KnowledgeImportService
from app.modules.knowledge.domain.normalization import (
    ExportValidationError,
    NORMALIZER_VERSION,
    digest,
)
from app.modules.knowledge.infrastructure.storage import table
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.schema_baseline import postgres_comment_snapshot
from backend.tests.test_knowledge_import import export_row, prepare


def record(
    body="步骤：提交合成订单。\n实际：E_TEST。\n预期：成功。", solution="增加合成参数校验。"
):
    return {
        "normalizer_version": NORMALIZER_VERSION,
        "title": "合成缺陷",
        "source_project_name": "合成项目",
        "body_text": body,
        "attributes": {"solution_text": solution, "module_names": ["合成模块"]},
        "completeness": {"inline_image_count": 1, "discussion_count": 1},
    }


def test_short_problem_whole_solution_separate_and_citation_coordinates():
    value = record()
    result = prepare_chunks(value)
    assert len(result.chunks) == 2
    problem, solution = result.chunks
    assert problem["evidence_text"] == value["body_text"]
    assert "标题：合成缺陷" in problem["embedding_text"]
    assert "问题片段：" in solution["embedding_text"]
    assert "images_not_collected" in solution["quality_flags"]
    for chunk in result.chunks:
        assert (
            chunk["evidence_text"]
            == result.normalized_fields[chunk["source_field"]][
                chunk["source_start"] : chunk["source_end"]
            ]
        )
    assert prepare_chunks(value).output_hash == result.output_hash


@pytest.mark.parametrize(
    "body",
    [
        "合成字符" * 4000,
        "步骤：合成输入。\n\n实际结果：合成失败。\n" * 150,
        "```python\n" + "    value = input_value  # E_SYNTHETIC\n" * 100 + "```\n结尾证据",
        "A" * 900 + "\n```python\n" + "    value = 1\n" * 40 + "```\n" + "B" * 2000,
        "行" + "\n" * 4000 + "尾部证据",
        "首行\n" + "日志" * 10000 + "\n尾部证据",
        "🧪中文é\t" * 3000,
    ],
)
def test_long_content_never_loses_nonwhitespace_or_tail(body):
    result = prepare_chunks(record(body, None))
    validate_chunks(result)
    covered = [False] * len(result.normalized_fields["body_text"])
    for chunk in result.chunks:
        assert chunk["char_count"] <= 1200
        assert chunk["embedding_char_count"] <= 1800
        covered[chunk["source_start"] : chunk["source_end"]] = [True] * chunk["char_count"]
    assert all(
        covered[i] or char.isspace() for i, char in enumerate(result.normalized_fields["body_text"])
    )
    assert result.chunks[-1]["source_end"] == len(result.normalized_fields["body_text"])


def test_small_fenced_block_remains_whole():
    fenced = "```python\n" + "    print('synthetic')\n" * 20 + "```"
    body = "前置" * 440 + "\n" + fenced + "\n" + "后置" * 600
    result = prepare_chunks(record(body, None))
    assert any(fenced in chunk["evidence_text"] for chunk in result.chunks)


def test_cleaning_preserves_code_and_does_not_decode_or_fold():
    value = "\n\r\n    if a &lt; b:\r\n\t  code = 'Ａ  01'\x00\n\n"
    assert clean_text(value) == "    if a &lt; b:\n\t  code = 'Ａ  01'"


@pytest.mark.parametrize(
    "solution,state",
    [
        (None, "absent"),
        (" \n", "absent"),
        ("已修复。", "status_only"),
        ("已处理", "status_only"),
        ({}, "unsupported_type"),
    ],
)
def test_non_evidence_solutions_are_marked_not_invented(solution, state):
    result = prepare_chunks(record(solution=solution))
    assert result.quality["solution_state"] == state
    assert len(result.chunks) == 1


def test_duplicate_solution_and_short_but_meaningful_solution():
    assert (
        prepare_chunks(record("合成问题", "合成问题")).quality["solution_state"]
        == "duplicates_body"
    )
    assert len(prepare_chunks(record(solution="重启服务")).chunks) == 2


def test_context_truncation_never_cuts_evidence():
    source = record("X" * 1200)
    source["title"] = "标题" * 500
    source["attributes"]["environment_text"] = "环境" * 500
    result = prepare_chunks(source)
    assert result.chunks[0]["evidence_text"] == "X" * 1200
    assert "context_truncated" in result.chunks[0]["quality_flags"]
    assert len(result.chunks[0]["embedding_text"]) <= 1800


def test_random_boundary_coverage_and_determinism():
    rng = random.Random(20260916)
    for _ in range(70):
        text = "".join(
            rng.choice(["合成", "E_DEMO", "\n", "\n\n", "    x < y", "。 ", "```", "\t"])
            for _ in range(rng.randrange(1, 1800))
        )
        if text.strip():
            prepared = prepare_chunks(record(text, None))
            validate_chunks(prepared)
            assert prepare_chunks(record(text, None)).output_hash == prepared.output_hash


def test_rejects_bad_profile_empty_body_or_unknown_normalizer():
    with pytest.raises(ExportValidationError, match="profile_invalid"):
        prepare_chunks(record(), replace(DEFAULT_PROFILE, overlap_chars=2000))
    with pytest.raises(ExportValidationError, match="body_empty"):
        prepare_chunks(record(" \n\t"))
    value = record()
    value["normalizer_version"] = "unverified"
    with pytest.raises(ExportValidationError, match="source_profile_unsupported"):
        prepare_chunks(value)


@pytest.fixture
def database():
    db = Database("sqlite:///:memory:")
    Migrator(db, default_migrations_dir(), migrator_build="knowledge-chunks-test").run()
    yield db
    db.close()


def import_rows(database, tmp_path, rows, *, source="synthetic_source", base="synthetic_base"):
    return KnowledgeImportService(ImportRepository(database)).import_export(
        prepare(tmp_path, rows), source_code=source, knowledge_base_code=base
    )


def import_historical_rows(database, tmp_path, rows):
    """仅准备发布/同步表引入前的迁移夹具；不能放宽生产缺表门禁。"""

    class HistoricalFixtureRepository(ImportRepository):
        def _assert_direct_write_allowed(self, source_id, base_id):
            pass

    assert database.execute_one("select max(version) as head from schema_migration")["head"] < "142"
    return KnowledgeImportService(HistoricalFixtureRepository(database)).import_export(
        prepare(tmp_path, rows),
        source_code="synthetic_source",
        knowledge_base_code="synthetic_base",
    )


def run(
    database, *, count=1, commit=True, profile=DEFAULT_PROFILE, base="synthetic_base", **kwargs
):
    return ChunkService(ChunkRepository(database, profile=profile)).run(
        knowledge_base_code=base, expected_count=count, commit=commit, **kwargs
    )


def source_fingerprint(database, *, include_observation=True):
    data = {}
    for name in (
        "source",
        "document",
        "document_revision",
        "knowledge_base",
        "knowledge_base_document",
        "import_run",
        "document_relation",
    ):
        rows = database.execute(f"select * from {table(database, name)}")
        if name == "document" and not include_observation:
            for row in rows:
                assert row.pop("source_observed_stamp_raw", None) is None
        data[name] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return digest(data)


def test_dry_run_commit_replay_and_originals_unchanged(database, tmp_path):
    import_rows(database, tmp_path, [export_row()])
    before = source_fingerprint(database)
    preview = run(database, commit=False)
    assert not database.execute('select * from "knowledge.document_chunk_set"')
    first = run(database)
    replay = run(database)
    assert first["counts"]["created"] == replay["counts"]["reused"] == 1
    assert preview["output_hash"] == first["output_hash"] == replay["output_hash"]
    assert source_fingerprint(database) == before
    assert not database.execute("pragma foreign_key_check")


def test_revision_and_profile_version_create_new_sets(database, tmp_path):
    row = export_row()
    import_rows(database, tmp_path, [row])
    run(database)
    revised = deepcopy(row)
    revised[0]["desc"] += "合成修订"
    revised[0]["server_update_stamp"] += 100
    import_rows(database, tmp_path, [revised])
    assert run(database)["counts"]["created"] == 1
    assert (
        run(database, profile=replace(DEFAULT_PROFILE, version="ones-text-chunks/test-v2"))[
            "counts"
        ]["created"]
        == 1
    )
    assert len(database.execute('select id from "knowledge.document_chunk_set"')) == 3


def test_middle_chunk_write_failure_rolls_back_whole_set_then_resumes(
    database, tmp_path, monkeypatch
):
    import_rows(database, tmp_path, [export_row(), export_row(2)])
    import app.modules.knowledge.infrastructure.chunk_repository as module

    original = module.insert
    sets = 0

    def fail(db, name, values, **kwargs):
        nonlocal sets
        if name == "document_chunk_set":
            sets += 1
        if sets == 2 and name == "document_chunk" and values["ordinal"] == 1:
            raise RuntimeError("synthetic non-public failure")
        return original(db, name, values, **kwargs)

    monkeypatch.setattr(module, "insert", fail)
    with pytest.raises(ExportValidationError, match="^knowledge_chunk_processing_failed$"):
        run(database, count=2)
    assert len(database.execute('select id from "knowledge.document_chunk_set"')) == 1
    monkeypatch.setattr(module, "insert", original)
    result = run(database, count=2)
    assert result["counts"]["created"] == result["counts"]["reused"] == 1


@pytest.mark.parametrize(
    "target,column", [("document_chunk", "evidence_hash"), ("document_chunk_set", "profile_hash")]
)
def test_existing_tampered_result_fails_closed(database, tmp_path, target, column):
    import_rows(database, tmp_path, [export_row()])
    run(database)
    database.execute(f"update {table(database, target)} set {column}=?", ("0" * 64,))
    with pytest.raises(ExportValidationError, match="stored_result_conflict"):
        run(database)


def test_stale_input_or_removed_membership_not_saved(database, tmp_path, monkeypatch):
    import_rows(database, tmp_path, [export_row()])
    original = ChunkRepository.save

    def remove(self, *args):
        self.database.execute("update \"knowledge.knowledge_base_document\" set state='removed'")
        return original(self, *args)

    monkeypatch.setattr(ChunkRepository, "save", remove)
    with pytest.raises(ExportValidationError, match="source_changed"):
        run(database)
    assert not database.execute('select * from "knowledge.document_chunk_set"')


def test_expected_count_mismatch_before_writes(database, tmp_path):
    import_rows(database, tmp_path, [export_row()])
    with pytest.raises(ExportValidationError, match="count_mismatch"):
        run(database, count=2)
    assert not database.execute('select * from "knowledge.document_chunk_set"')


def test_keyset_pagination_more_than_one_page(database, tmp_path):
    import_rows(database, tmp_path, [export_row(i) for i in range(103)])
    assert run(database, count=103)["counts"]["created"] == 103
    assert run(database, count=103)["counts"]["reused"] == 103


def test_demo_never_loads_secrets_or_database(monkeypatch, capsys):
    def forbidden():
        raise AssertionError("must not load settings")

    monkeypatch.setattr("app.cli.prepare_knowledge_chunks.load_settings", forbidden)
    assert main(["--demo"]) == 0
    assert "synthetic_demo" in capsys.readouterr().out
    assert main(["--demo", "--commit"]) == 1


@pytest.mark.skipif(
    not os.getenv("KNOWLEDGE_TEST_POSTGRES_DSN"), reason="requires isolated PostgreSQL"
)
def test_real_postgres_chunk_storage_constraints_and_replay(tmp_path):
    db = Database(os.environ["KNOWLEDGE_TEST_POSTGRES_DSN"])
    try:
        Migrator(db, default_migrations_dir(), migrator_build="knowledge-chunks-isolated").run()
        source, base = "synthetic_" + uuid.uuid4().hex, "synthetic_" + uuid.uuid4().hex
        import_rows(db, tmp_path, [export_row(), export_row(2)], source=source, base=base)
        first = run(db, count=2, base=base)
        second = run(db, count=2, base=base)
        assert first["output_hash"] == second["output_hash"]
        assert second["counts"]["reused"] == 2
        sets = db.execute(
            "select id,document_id,document_revision_id,normalized_fields from knowledge.document_chunk_set where document_id in (select id from knowledge.document where source_id=(select id from knowledge.source where code=?)) order by id",
            (source,),
        )
        assert isinstance(sets[0]["normalized_fields"], dict)
        with pytest.raises(Exception):
            with db.unit_of_work():
                db.execute(
                    "update knowledge.document_chunk_set set document_id=? where id=?",
                    (sets[1]["document_id"], sets[0]["id"]),
                )
        with pytest.raises(Exception):
            with db.unit_of_work():
                db.execute(
                    "update knowledge.document_chunk set source_end=source_end+1 where chunk_set_id=?",
                    (sets[0]["id"],),
                )
        comments = postgres_comment_snapshot(db)
        assert sum(name.startswith("knowledge.") for name in comments["tables"]) == 11
        for name in ("document_chunk_set", "document_chunk"):
            count = db.execute_one(
                "select count(*) as n from information_schema.columns where table_schema='knowledge' and table_name=?",
                (name,),
            )["n"]
            assert (
                sum(key.startswith("knowledge." + name + ".") for key in comments["columns"])
                == count
            )
    finally:
        db.close()
