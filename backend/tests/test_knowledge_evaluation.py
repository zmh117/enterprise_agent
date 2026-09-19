from copy import deepcopy
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from app.cli import evaluate_knowledge as cli
from app.modules.knowledge.application.evaluation import (
    OfflineEvaluation,
    latency_summary,
    score_documents,
)
from app.modules.knowledge.domain.evaluation import (
    MAX_DATASET_BYTES,
    EvaluationError,
    parse_dataset,
)
from app.modules.knowledge.infrastructure.evaluation_dataset import load_dataset
from app.modules.knowledge.domain.vector_contract import VectorError
from backend.tests.test_knowledge_chunks import source_fingerprint
from backend.tests.test_knowledge_vectors import prepared as vector_fixture

prepared = vector_fixture


def sample():
    return {
        "contract": "knowledge-evaluation/v1",
        "dataset_version": "synthetic-v1",
        "basis": "synthetic",
        "labels_complete": False,
        "knowledge_base_code": "synthetic_base",
        "source_id": "00000000-0000-0000-0000-000000000001",
        "annotation": {"origin": "synthetic_fixture", "reviewed": True},
        "cases": [
            {
                "query_id": "q1",
                "query": "合成问题不得进入汇总",
                "category": "paraphrase",
                "no_answer": False,
                "relevant": [{"kind": "work_item", "id": "synthetic_item_1"}],
            }
        ],
    }


def write_dataset(tmp_path, value=None):
    tmp_path.chmod(0o700)
    target = tmp_path / "labels.json"
    target.write_text(json.dumps(sample() if value is None else value))
    target.chmod(0o600)
    return target


def setup_evaluation(prepared):
    db, service, snapshot = prepared
    service.build("synthetic-eval-v1", snapshot)
    value = sample()
    value["source_id"] = db.execute_one('select id from "knowledge.source"')["id"]
    return db, service, value


def test_strict_format_hash_and_repr():
    value = sample()
    dataset = parse_dataset(value)
    assert dataset.digest == parse_dataset(deepcopy(value)).digest
    assert dataset.cases[0].query not in repr(dataset) + repr(dataset.cases[0])
    value["cases"][0]["query"] += "另一个问法"
    assert parse_dataset(value).digest != dataset.digest


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.update(unknown="hidden"),
        lambda x: x.update(cases=[]),
        lambda x: x.update(cases=x["cases"] * 501),
        lambda x: x.update(source_id="display-name"),
        lambda x: x.update(labels_complete=1),
        lambda x: x["annotation"].update(reviewed=False),
        lambda x: x["annotation"].update(reviewed=1),
        lambda x: x["annotation"].update(origin="model_generated"),
        lambda x: x.update(basis="human"),
        lambda x: x["cases"][0].pop("relevant"),
        lambda x: x["cases"][0].update(relevant=[]),
        lambda x: x["cases"][0].update(no_answer=True),
        lambda x: x["cases"][0].update(no_answer=0),
        lambda x: x["cases"][0].update(query="   "),
        lambda x: x["cases"][0].update(query="字" * 2001),
        lambda x: x["cases"][0].update(category="pipeline_probe"),
        lambda x: x["cases"].append(deepcopy(x["cases"][0])),
        lambda x: x["cases"][0]["relevant"].append(deepcopy(x["cases"][0]["relevant"][0])),
        lambda x: x["cases"][0]["relevant"][0].update(kind="document", id="not-uuid"),
    ],
)
def test_invalid_dataset_has_only_stable_error(mutate):
    value = sample()
    mutate(value)
    with pytest.raises(EvaluationError) as error:
        parse_dataset(value)
    assert str(error.value) == "knowledge_evaluation_dataset_invalid"


def test_human_and_self_query_are_separate():
    value = sample()
    value.update(basis="human")
    value["annotation"]["origin"] = "human_reviewed"
    assert parse_dataset(value).basis == "human"
    value.update(basis="self_query")
    value["annotation"]["origin"] = "pipeline_probe"
    value["cases"][0]["category"] = "pipeline_probe"
    assert parse_dataset(value).basis == "self_query"


def test_file_permissions_size_duplicate_json_keys_and_links(tmp_path):
    path = write_dataset(tmp_path)
    assert load_dataset(path).basis == "synthetic"
    path.chmod(0o644)
    with pytest.raises(EvaluationError, match="permissions"):
        load_dataset(path)
    path.chmod(0o600)
    tmp_path.chmod(0o755)
    with pytest.raises(EvaluationError, match="permissions"):
        load_dataset(path)
    tmp_path.chmod(0o700)
    path.write_bytes(b" " * (MAX_DATASET_BYTES + 1))
    with pytest.raises(EvaluationError, match="input_limit"):
        load_dataset(path)
    path.write_text('{"hidden":"body","hidden":"label"}')
    with pytest.raises(EvaluationError, match="dataset_invalid"):
        load_dataset(path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(EvaluationError):
        load_dataset(link)
    with pytest.raises(EvaluationError):
        load_dataset(tmp_path / "missing")


def test_document_metrics_dedupe_top10_misses_and_visible_denominator():
    relevant = frozenset({"a", "b"})
    scores = score_documents(relevant, ["noise", "a", "a", "b"])
    assert scores.recall == 1 and scores.reciprocal_rank == 0.5
    assert score_documents(relevant, ["a"]).recall == 0.5
    assert score_documents(relevant, ["noise"]).reciprocal_rank == 0
    assert score_documents(relevant, [str(i) for i in range(10)] + ["a"]).recall == 0
    assert score_documents(relevant, ["a"], visible_relevant=frozenset({"a"})).recall == 1
    no_visible = score_documents(relevant, [], visible_relevant=frozenset())
    assert no_visible.recall is None and no_visible.no_answer_false_positive is False
    assert score_documents(frozenset(), ["noise"]).no_answer_false_positive is True
    with pytest.raises(EvaluationError, match="visibility_invalid"):
        score_documents(relevant, [], visible_relevant=frozenset({"unrelated"}))
    assert latency_summary([1, 2, 100]) == {"p50_ms": 2, "p95_ms": 100}
    assert latency_summary([]) == {"p50_ms": None, "p95_ms": None}


def test_offline_runner_reuses_kernel_without_writes_and_redacts(prepared, capsys, caplog):
    db, service, value = setup_evaluation(prepared)
    value["cases"][0]["relevant"].append({"kind": "work_item", "id": "synthetic_item_2"})
    value["cases"].append(
        {
            "query_id": "q2",
            "query": "合成无答案",
            "category": "no_answer",
            "no_answer": True,
            "relevant": [],
        }
    )
    before = source_fingerprint(db)
    writes = service.qdrant.writes
    report = OfflineEvaluation(service).run(parse_dataset(value), "synthetic-eval-v1")
    assert report["recall_at_10"] == report["mrr_at_10"] == 1
    assert report["answerable_cases"] == 1 and report["no_answer"]["false_positive_rate"] == 1
    assert report["basis"] == "synthetic" and report["mode"] == "offline_dense"
    assert report["recall_scope"] == "labeled_set_only" and not report["business_acceptance"]
    assert not report["authorization_verified"] and report["end_to_end_latency"] is None
    assert report["parameters"] == {
        "top_k": 10,
        "candidate_limit": 200,
        "metrics_version": "document-v1",
    }
    assert len(report["code_hash"]) == len(report["dataset_hash"]) == 64
    assert service.qdrant.writes == writes and source_fingerprint(db) == before
    output = json.dumps(report, ensure_ascii=False) + capsys.readouterr().out + caplog.text
    assert "合成问题不得进入汇总" not in output and "synthetic_item_1" not in output


def test_missing_label_or_wrong_source_rejected_before_embedding(prepared):
    db, service, value = setup_evaluation(prepared)
    encoded = service.embedding.encoded
    value["cases"][0]["relevant"][0]["id"] = "not-in-corpus"
    with pytest.raises(EvaluationError, match="label_unavailable"):
        OfflineEvaluation(service).run(parse_dataset(value), "synthetic-eval-v1")
    assert service.embedding.encoded == encoded
    value["source_id"] = sample()["source_id"]
    with pytest.raises(EvaluationError, match="source_invalid"):
        OfflineEvaluation(service).run(parse_dataset(value), "synthetic-eval-v1")


def test_stale_document_cannot_produce_report(prepared, monkeypatch):
    db, service, value = setup_evaluation(prepared)
    original = service.query

    def remove(*args, **kwargs):
        result = original(*args, **kwargs)
        db.execute("update \"knowledge.knowledge_base_document\" set state='removed'")
        return result

    monkeypatch.setattr(service, "query", remove)
    with pytest.raises(VectorError):
        OfflineEvaluation(service).run(parse_dataset(value), "synthetic-eval-v1")


def test_failures_are_counted_not_silent_misses_or_no_answer_success(prepared, monkeypatch):
    _, service, value = setup_evaluation(prepared)
    value["cases"].append(
        {
            "query_id": "q2",
            "query": "合成无答案",
            "category": "no_answer",
            "no_answer": True,
            "relevant": [],
        }
    )
    monkeypatch.setattr(service, "query", Mock(side_effect=RuntimeError("hidden provider body")))
    report = OfflineEvaluation(service).run(parse_dataset(value), "synthetic-eval-v1")
    assert report["failed_cases"] == 2 and report["failures"] == {"internal_error": 2}
    assert report["recall_at_10"] == report["mrr_at_10"] == 0
    assert (
        report["no_answer"]["completed"] == 0 and report["no_answer"]["false_positive_rate"] is None
    )
    assert "hidden provider body" not in json.dumps(report)


def test_cli_validates_without_database_and_redacts_all_errors(tmp_path, monkeypatch, capsys):
    path = write_dataset(tmp_path)
    forbidden = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(cli, "load_settings", forbidden)
    assert cli.main(["--dataset", str(path), "--validate-only"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["event"] == "knowledge_evaluation_dataset_valid"
    assert not forbidden.called
    assert (
        cli.main(["--dataset", str(tmp_path / "hidden-labels"), "--index-code", "synthetic"]) == 1
    )
    assert cli.main(["--secret-option", "hidden-body"]) == 1
    output = capsys.readouterr()
    assert "hidden" not in output.out + output.err and not output.err


def test_real_label_directory_is_git_ignored():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "check-ignore", ".local/knowledge-evaluation/labels.json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_tracked_example_is_synthetic_only():
    root = Path(__file__).resolve().parents[2]
    value = json.loads((root / "knowledge/evaluation/synthetic.dataset.json").read_text())
    assert parse_dataset(value).basis == "synthetic"
