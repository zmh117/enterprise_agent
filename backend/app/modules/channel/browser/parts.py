"""Validate bounded projections before writing any recording content."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import zlib
from typing import Any

from app.modules.channel.browser.http import deny
from app.modules.channel.browser.recordings import MAX_PART_BYTES, _unique_keys, contract
from app.shared.database import Database

PROTECTED_KEY = re.compile(
    r"(authorization|cookie|password|passwd|credential|secret|token|privatekey|apikey|modelkey|sessionid|sessionkey|csrf|xsrf|accesskey|signingkey|密码|令牌)"
    r"|^(pwd|session|sid|jwt|signature|ticket|rawbody|rawmessage|postdata|requestheaders|responseheaders|setcookie|headers)$",
    re.I,
)
PROTECTED_VALUE = re.compile(
    r"(?:\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_.=-]{4,}|-----BEGIN [^\n]*PRIVATE KEY-----"
    r"|\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|(?:^|[\r\n])\s*(?:Authorization|Cookie|Set-Cookie)\s*:)",
    re.I,
)


def checked_value(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("nesting limit")
    if isinstance(value, dict):
        for name in ("name", "key", "field", "fieldName", "header"):
            label = value.get(name)
            if isinstance(label, str) and PROTECTED_KEY.search(re.sub(r"[\s._-]+", "", label)):
                raise ValueError("protected named value")
        for key, child in value.items():
            if PROTECTED_KEY.search(re.sub(r"[\s._-]+", "", key)) or PROTECTED_VALUE.search(key):
                raise ValueError("protected field")
            checked_value(child, depth + 1)
    elif isinstance(value, list):
        for item in value:
            checked_value(item, depth + 1)
    elif isinstance(value, str):
        value.encode("utf-8")
        if (
            PROTECTED_VALUE.search(value)
            or re.search(r"[a-z][a-z0-9+.-]{0,15}://[^ /:@]+:[^ /@]+@", value, re.I)
            or value.lstrip().startswith(("{", "[", "<!DOCTYPE", "<html", "<?xml"))
        ):
            raise ValueError("protected content")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("invalid number")


def validate_row(row: dict[str, Any]) -> None:
    if row.get("kind") == "action":
        detail = row.get("details")
        value = detail.get("value") if isinstance(detail, dict) else None
        target = value.get("target") if isinstance(value, dict) else None
        if isinstance(target, dict) and (
            target.get("type") == "password"
            or target.get("inputType") == "password"
            or re.search(
                r"current-password|new-password|one-time-code",
                str(target.get("autocomplete", "")),
                re.I,
            )
        ):
            raise ValueError("protected input")
    checked_value(row)
    if not contract("EvidenceRow").is_valid(row):
        raise ValueError


def decode_part(
    wire: bytes, encoding: str, expected: dict[str, Any]
) -> tuple[bytes, list[dict[str, Any]]]:
    if len(wire) > MAX_PART_BYTES + 1024:
        raise deny("quota_exceeded", 413)
    raw = wire
    if encoding == "gzip":
        decoder = zlib.decompressobj(wbits=31)
        try:
            raw = decoder.decompress(wire, MAX_PART_BYTES + 1)
        except zlib.error:
            raise deny("invalid_request", 422) from None
        if len(raw) > MAX_PART_BYTES or decoder.unconsumed_tail:
            raise deny("quota_exceeded", 413)
        if not decoder.eof or decoder.unused_data:
            raise deny("invalid_request", 422)
    elif encoding != "identity":
        raise deny("invalid_request", 415)
    if len(raw) != expected["size_bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise deny("manifest_conflict", 409)
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise deny("invalid_request", 422)
    rows = []
    previous = None
    try:
        for line in raw[:-1].split(b"\n"):
            row = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_keys)
            if not isinstance(row, dict):
                raise ValueError
            validate_row(row)
            identity = (
                row["kind"],
                row["requestKey"] if row["kind"] == "request" else row["eventId"],
            )
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", identity[1]) or (
                previous and previous >= identity
            ):
                raise ValueError
            previous = identity
            rows.append(row)
    except (ValueError, OverflowError, RecursionError):
        raise deny("invalid_request", 422) from None
    return raw, rows


def record_index(db: Database, rid: str, number: int, rows: list[dict[str, Any]]) -> None:
    # Keep each statement within SQLite's bind-parameter limit.
    def insert(table: str, columns: str, values: list[tuple[Any, ...]]) -> None:
        for start in range(0, len(values), 64):
            batch = values[start : start + 64]
            pattern = "(" + ",".join("?" for _ in batch[0]) + ")"
            db.execute(
                f"insert into {table}({columns}) values "
                + ",".join(pattern for _ in batch)
                + " on conflict do nothing",
                tuple(x for row in batch for x in row),
            )

    indexes = []
    links = []
    for pos, row in enumerate(rows):
        source = row.get("requestKey", row.get("eventId"))
        indexes.append(
            (
                rid,
                row["kind"],
                source,
                row["offset_ms"],
                number,
                pos,
                row.get("path_template"),
                row.get("method"),
                row.get("http_status"),
                row.get("business_outcome"),
                row.get("action"),
            )
        )
        for link in row.get("associations", []):
            links.append((rid, source, link["eventId"], link["basis"]))
    insert(
        "browser_recording_evidence",
        "recording_id,kind,source_id,offset_ms,part_number,line_number,path_template,method,http_status,business_outcome,action",
        indexes,
    )
    count = db.execute_one(
        "select count(*) as n from browser_recording_evidence where recording_id=? and part_number=?",
        (rid, number),
    )
    if not count or count["n"] != len(rows):
        raise deny("manifest_conflict", 409)
    insert("browser_recording_association", "recording_id,request_key,action_id,basis", links)
    db.execute(
        "update browser_recording_part set received_at=? where recording_id=? and part_number=?",
        (int(time.time()), rid, number),
    )


def check_coverage(db: Database, rec: dict[str, Any]) -> None:
    coverage = json.loads(rec["coverage_json"])
    digests = {kind: hashlib.sha256() for kind in ("action", "request")}
    counts = {"action": 0, "request": 0}
    position = (-1, -1)
    previous = ("", "")
    while True:
        page = db.execute(
            """select kind,source_id,part_number,line_number from browser_recording_evidence
            where recording_id=? and (part_number,line_number)>(?,?)
            order by part_number,line_number limit 1024""",
            (rec["id"], *position),
        )
        for item in page:
            identity = (item["kind"], item["source_id"])
            if identity <= previous:
                raise deny("manifest_conflict", 409)
            kind, source = previous = identity
            digests[kind].update(source.encode("ascii") + b"\n")
            counts[kind] += 1
            position = item["part_number"], item["line_number"]
        if len(page) < 1024:
            break
    for kind, digest in digests.items():
        expected = coverage[kind + "s"]
        if counts[kind] != expected["shareable"] or digest.hexdigest() != expected["ids_sha256"]:
            raise deny("manifest_conflict", 409)
    dangling = db.execute_one(
        """select 1 from browser_recording_association a where recording_id=?
        and not exists(select 1 from browser_recording_evidence e where e.recording_id=a.recording_id
        and e.kind='action' and e.source_id=a.action_id) limit 1""",
        (rec["id"],),
    )
    if dangling:
        raise deny("manifest_conflict", 409)
