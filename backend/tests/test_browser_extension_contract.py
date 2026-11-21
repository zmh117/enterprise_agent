import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2] / "contracts/browser-extension/v1"
GOLDEN = ROOT / "golden"
SCHEMA = json.loads((ROOT / "protocol.schema.json").read_text())


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{name}"})


def test_wire_examples_match_closed_contracts() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    events = set()
    receipts = {}
    for item in json.loads((GOLDEN / "conversation.json").read_text()):
        body = item["body"]
        validator(item["contract"]).validate(body)
        if item["contract"] == "AnswerEvent":
            events.add(body["event"])
        if item["contract"] == "MessageReceipt":
            assert receipts.setdefault(body["job_id"], body) == body
    assert events == {"status", "answer_delta", "reset", "completed", "failed"}


@pytest.mark.parametrize("label", ["a", "b"])
def test_manifest_matches_transmitted_bytes_and_source_ids(label: str) -> None:
    request = json.loads((GOLDEN / f"init-{label}.json").read_text())
    validator("InitRecording").validate(request)
    manifest = request["manifest"]
    raw = (GOLDEN / f"recording-{label}.ndjson").read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert raw == b"".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        for row in rows
    )
    assert manifest["parts"] == [
        {"number": 0, "uncompressed_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    ]
    for row in rows:
        validator("EvidenceRow").validate(row)
    for kind, key in (("action", "eventId"), ("request", "requestKey")):
        ids = sorted(row[key] for row in rows if row["kind"] == kind)
        count = manifest["coverage"][kind + "s"]
        assert count["saved"] == count["platform_excluded"] + count["shareable"]
        assert len(set(ids)) == len(ids) == count["shareable"]
        joined = "".join(i + "\n" for i in ids).encode()
        assert hashlib.sha256(joined).hexdigest() == count["ids_sha256"]


def test_new_business_fields_are_queryable_on_an_unknown_path() -> None:
    row = json.loads((GOLDEN / "recording-b.ndjson").read_bytes())
    assert row["path_template"] is None
    assert row["request_details"]["value"]["新增业务字段"][0]["数量"] == 3.5
    assert row["request_details"]["omissions"] == [{"path": "/sessionToken", "reason": "protected"}]
    validate = validator("EvidenceRow").is_valid
    assert validate(row)
    assert not validate({**row, "body": "synthetic"})
    assert not validate({**row, "request_fields": "included"})
    assert not validate({**row, "response_details": row["request_details"]})
    contaminated = {"value": [{"nested": {"Cookie": "synthetic-marker"}}], "omissions": []}
    assert not validate({**row, "request_fields": "included", "request_details": contaminated})
    assert not validator("Manifest").is_valid(
        {**json.loads((GOLDEN / "init-b.json").read_bytes())["manifest"], "projection_version": "1"}
    )


def test_search_and_question_scopes_remain_closed() -> None:
    assert not validator("SearchRecording").is_valid({"recording_id": "another"})
    assert not validator("CreateMessage").is_valid({"client_message_id": "m", "question": " "})
