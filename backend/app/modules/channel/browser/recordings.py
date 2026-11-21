"""Admission and resume receipts for a sealed browser recording."""

from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator

from app.modules.channel.browser.http import deny
from app.shared.database import Database

MIB = 1024 * 1024
MAX_MANIFEST_BYTES = MIB
MAX_PART_BYTES = MIB
MAX_RECORDING_BYTES = 256 * MIB
MAX_STAGED_BYTES_PER_OWNER = 512 * MIB
MAX_STAGED_RECORDINGS = 32
MAX_ROWS = 1_000_000
STAGING_SECONDS = 24 * 60 * 60
EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


@lru_cache(maxsize=4)
def contract(name: str) -> Draft202012Validator:
    root = Path(__file__).resolve().parents[5]
    schema = json.loads((root / "contracts/browser-extension/v1/protocol.schema.json").read_text())
    return Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{name}"})


def _reject_float(_: str) -> None:
    raise ValueError("integer required")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_initialization(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise deny("quota_exceeded", 413)
    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_keys,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
        if not isinstance(data, dict) or not contract("InitRecording").is_valid(data):
            raise ValueError("invalid manifest")
    except (ValueError, RecursionError):
        raise deny("invalid_request", 422) from None
    manifest = data["manifest"]
    counts = [manifest["coverage"][name] for name in ("actions", "requests")]
    for count in counts:
        if count["shareable"] + count["platform_excluded"] != count["saved"]:
            raise deny("invalid_request", 422)
        if not count["shareable"] and count["ids_sha256"] != EMPTY_DIGEST:
            raise deny("invalid_request", 422)
    size = 0
    for number, part in enumerate(manifest["parts"]):
        if part["number"] != number or not part["uncompressed_bytes"]:
            raise deny("invalid_request", 422)
        if part["uncompressed_bytes"] > MAX_PART_BYTES:
            raise deny("quota_exceeded", 413)
        size += part["uncompressed_bytes"]
    rows = sum(count["shareable"] for count in counts)
    if size > MAX_RECORDING_BYTES or rows > MAX_ROWS:
        raise deny("quota_exceeded", 413)
    if bool(rows) != bool(size) or len(manifest["parts"]) > rows:
        raise deny("invalid_request", 422)
    return data


def manifest_digest(manifest: dict[str, Any]) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def progress(db: Database, row: dict[str, Any], now: int) -> dict[str, Any]:
    if row["state"] in {"expired", "upload_expired"} or row["expires_at"] <= now:
        raise deny(
            "upload_expired" if row["state"] in {"uploading", "upload_expired"} else "not_found",
            410,
        )
    missing = db.execute(
        """select part_number from browser_recording_part where recording_id=?
           and received_at is null order by part_number""",
        (row["id"],),
    )
    return {
        "recording_id": row["id"],
        "state": row["state"],
        "missing_parts": [p["part_number"] for p in missing],
    }


def reserve(
    db: Database, *, origin: str, user: str, app: str, active: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any]:
    """Caller holds the owner row lock inside the authorization transaction."""
    now = int(time.time())
    manifest = data["manifest"]
    scope = active["scope_ref"]
    digest = manifest_digest(manifest)
    attempt = data["upload_attempt_id"]
    row = db.execute_one(
        """select r.* from browser_recording_upload_attempt a join browser_recording r on r.id=a.recording_id
           where a.scope_ref=? and a.attempt_id=?""",
        (scope, attempt),
    )
    if row:
        if row["manifest_digest"] != digest:
            raise deny("manifest_conflict", 409)
        return progress(db, row, now)

    version = (
        scope,
        manifest["local_recording_id"],
        manifest["checkpoint"],
        manifest["projection_version"],
    )
    row = db.execute_one(
        """select * from browser_recording where scope_ref=? and local_recording_id=? and checkpoint=?
           and projection_version=? and state <> 'upload_expired'""",
        version,
    )
    if row and row["manifest_digest"] != digest:
        raise deny("manifest_conflict", 409)
    if row and row["state"] == "uploading" and row["expires_at"] <= now:
        db.execute("update browser_recording set state='upload_expired' where id=?", (row["id"],))
        row = None
    if not row:
        row = _create(db, origin, user, app, active, manifest, digest, now)
    result = progress(db, row, now)
    db.execute(
        "insert into browser_recording_upload_attempt(scope_ref,attempt_id,recording_id) values(?,?,?)",
        (scope, attempt, row["id"]),
    )
    return result


def _create(
    db: Database,
    origin: str,
    user: str,
    app: str,
    active: dict[str, Any],
    manifest: dict[str, Any],
    digest: str,
    now: int,
) -> dict[str, Any]:
    usage = db.execute_one(
        """select count(distinct r.id) as recordings, coalesce(sum(p.size_bytes),0) as reserved
           from browser_recording r left join browser_recording_part p on p.recording_id=r.id
           where r.origin=? and r.user_id=? and r.state='uploading' and r.expires_at>?""",
        (origin, user, now),
    )
    parts = manifest["parts"]
    if (
        not usage
        or usage["recordings"] >= MAX_STAGED_RECORDINGS
        or (
            usage["reserved"] + sum(p["uncompressed_bytes"] for p in parts)
            > MAX_STAGED_BYTES_PER_OWNER
        )
    ):
        raise deny("quota_exceeded", 413)
    recording = uuid4().hex
    deadline = now + STAGING_SECONDS
    db.execute(
        """insert into browser_recording(id,origin,user_id,application_id,publication_id,scope_ref,
           local_recording_id,checkpoint,projection_version,manifest_digest,coverage_json,state,created_at,expires_at)
           values (?,?,?,?,?,?,?,?,?,?,?,'uploading',?,?)""",
        (
            recording,
            origin,
            user,
            app,
            active["publication_id"],
            active["scope_ref"],
            manifest["local_recording_id"],
            manifest["checkpoint"],
            manifest["projection_version"],
            digest,
            json.dumps(manifest["coverage"], separators=(",", ":")),
            now,
            deadline,
        ),
    )
    for start in range(0, len(parts), 100):
        batch = parts[start : start + 100]
        values = [(recording, p["number"], p["uncompressed_bytes"], p["sha256"]) for p in batch]
        db.execute(
            "insert into browser_recording_part(recording_id,part_number,size_bytes,sha256) values "
            + ",".join("(?,?,?,?)" for _ in batch),
            tuple(item for group in values for item in group),
        )
    return {"id": recording, "state": "uploading", "expires_at": deadline}
