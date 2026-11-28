"""Private evidence transport. Endpoints come from platform deployment, never from a request."""

import base64
import hashlib
import json
import os
import time
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.modules.channel.browser.http import deny
from app.modules.channel.browser.live_capture import CaptureId, LivePage
from app.modules.channel.browser.scope import fingerprint, scope_key
from app.modules.channel.browser.workshop_bindings import workshop_choices

PART_BYTES = 32 * 1024
LINE_BYTES = 64 * 1024
BATCH_BYTES = 512 * 1024
MAX_OBJECT = 40 * 1024 * 1024
KINDS = Literal["baseline", "action", "mutation", "request", "response", "request_end", "body"]


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: CaptureId
    seq: int = Field(ge=1, le=2**53 - 1)
    observed_ms: int = Field(ge=1, le=2**53 - 1)
    kind: KINDS
    event_digest: str = Field(pattern="^[0-9a-f]{64}$")
    event_bytes: int = Field(ge=1, le=MAX_OBJECT)
    number: int = Field(ge=0, lt=MAX_OBJECT // PART_BYTES)
    data: str = Field(min_length=4, max_length=4 * ((PART_BYTES + 2) // 3))


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recording_id: CaptureId
    source: LivePage
    parts: list[Part] = Field(min_length=1, max_length=64)


def endpoint(write: bool) -> str:
    url = os.getenv("BROWSER_EVIDENCE_WRITE_URL" if write else "BROWSER_EVIDENCE_READ_URL", "")
    expected = "evidence-alloy" if write else "evidence-loki"
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {expected, "127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        return url.rstrip("/")
    except ValueError:
        raise deny("live_evidence_unavailable", 503) from None


def client() -> httpx.Client:
    return httpx.Client(timeout=5, trust_env=False)


def public_scope(
    c: Any, origin: str, user: str, app: str, scope_ref: str, recording_id: str, source: LivePage
) -> dict[str, str]:
    row = c.database.execute_one(
        """select w.environment_id,w.base_id,w.workshop_id,w.rule_json
        from browser_live_recording r join browser_live_page p on p.recording_id=r.id
        join browser_workshop_binding w on w.id=p.binding_id and w.revision=p.revision
        join browser_workshop_binding head on head.id=w.id and head.is_head=1 and head.enabled=1
           and head.application_id=w.application_id
        where r.id=? and r.origin=? and r.user_id=? and r.application_id=? and r.scope_ref=?
        and p.tab_id=? and p.document_id=? and p.binding_id=? and p.revision=?""",
        (
            recording_id,
            origin,
            user,
            app,
            scope_ref,
            source.tab_id,
            source.document_id,
            source.binding_id,
            source.revision,
        ),
    )
    if not row or not any(scope_key(row) == scope_key(w) for w in workshop_choices(c, user, app)):
        raise deny("access_denied", 403)
    return {
        "tenant": fingerprint([origin]),
        "owner": fingerprint([origin, user]),
        "application": app,
        "environment": row["environment_id"],
        "base": row["base_id"] or "",
        "workshop": row["workshop_id"] or "",
        "site": fingerprint(json.loads(row["rule_json"])["origin"]),
        "recording_id": recording_id,
        "tab_id": source.tab_id,
        "document_id": source.document_id,
        "binding_id": source.binding_id,
        "revision": str(source.revision),
    }


def labels(scope: dict[str, str], kind: str) -> dict[str, str]:
    return {
        **{k: scope[k] for k in ("application", "environment", "site")},
        "dataset": "browser_evidence",
        "kind": kind,
        "format": "v1",
    }


def prepare_parts(c: Any, scope: dict[str, str], parts: list[Part]) -> dict[str, Any]:
    db = c.database
    streams: dict[str, list[list[str]]] = {}
    for part in parts:
        count = (part.event_bytes + PART_BYTES - 1) // PART_BYTES
        try:
            data = base64.b64decode(part.data, validate=True)
        except ValueError:
            raise deny("invalid_request", 422) from None
        digest = hashlib.sha256(data).hexdigest()
        if (
            part.number >= count
            or len(data) != min(PART_BYTES, part.event_bytes - part.number * PART_BYTES)
            or (count == 1 and digest != part.event_digest)
        ):
            raise deny("invalid_request", 422)
        recording = scope["recording_id"]
        key = (recording, part.event_id)
        facts = {
            "tab_id": scope["tab_id"],
            "document_id": scope["document_id"],
            "kind": part.kind,
            "event_digest": part.event_digest,
            "event_bytes": part.event_bytes,
            "part_count": count,
            "source_seq": part.seq,
            "observed_ms": part.observed_ms,
        }
        registered = db.execute_one(
            "select * from browser_live_evidence_part where recording_id=? and event_id=? limit 1",
            key,
        )
        if registered and any(registered[k] != v for k, v in facts.items()):
            raise deny("live_part_conflict", 409)
        old = db.execute_one(
            "select part_digest, received_ns from browser_live_evidence_part where recording_id=? and event_id=? and part_number=?",
            (*key, part.number),
        )
        if old and old["part_digest"] != digest:
            raise deny("live_part_conflict", 409)
        instant = old["received_ns"] if old else time.time_ns()
        if not old:
            db.execute(
                """insert into browser_live_evidence_part(recording_id,tab_id,document_id,event_id,part_number,part_digest,
                   event_digest,event_bytes,part_count,source_seq,observed_ms,received_ns,kind)
                   values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    recording,
                    scope["tab_id"],
                    scope["document_id"],
                    part.event_id,
                    part.number,
                    digest,
                    part.event_digest,
                    part.event_bytes,
                    count,
                    part.seq,
                    part.observed_ms,
                    instant,
                    part.kind,
                ),
            )
        line = json.dumps(
            {
                **scope,
                **part.model_dump(exclude={"data"}),
                "part_digest": digest,
                "part_count": count,
                "received_ns": str(instant),
                "data": part.data,
            },
            separators=(",", ":"),
        )
        if len(line.encode()) > LINE_BYTES:
            raise deny("quota_exceeded", 413)
        streams.setdefault(part.kind, []).append([str(instant), line])
    return {
        "streams": [
            {
                "stream": {**labels(scope, kind), "evidence_tenant": scope["tenant"]},
                "values": sorted(values, key=lambda x: int(x[0])),
            }
            for kind, values in streams.items()
        ]
    }


def forward(body: dict[str, Any]) -> None:
    try:
        with client() as http:
            response = http.post(endpoint(True) + "/loki/api/v1/push", json=body)
        if not 200 <= response.status_code < 300:
            raise deny("live_evidence_unavailable", 503)
    except httpx.HTTPError:
        raise deny("live_evidence_unavailable", 503) from None


def read_part(scope: dict[str, str], row: dict[str, Any]) -> bytes | None:
    selector = ",".join(k + "=" + json.dumps(v) for k, v in labels(scope, row["kind"]).items())
    check = {**scope, "event_id": row["event_id"], "number": row["part_number"]}
    filters = " ".join(
        "| " + k + "=" + json.dumps(str(check[k]))
        for k in ("owner", "recording_id", "event_id", "number")
    )
    start = row["received_ns"]
    query = {
        "query": "{" + selector + "} | json " + filters,
        "start": str(start),
        "end": str(start + 1),
        "limit": "4",
        "direction": "forward",
    }
    try:
        with (
            client() as http,
            http.stream(
                "GET",
                endpoint(False) + "/loki/api/v1/query_range",
                params=query,
                headers={"X-Scope-OrgID": scope["tenant"]},
            ) as resp,
        ):
            resp.raise_for_status()
            raw = bytearray()
            for chunk in resp.iter_bytes(32768):
                raw.extend(chunk)
                if len(raw) > 4 * LINE_BYTES + 8192:
                    raise ValueError
        result = json.loads(raw)
        if result["status"] != "success" or result["data"]["resultType"] != "streams":
            raise ValueError
        for stream in result["data"]["result"]:
            for instant, value in stream["values"]:
                line = json.loads(value)
                if instant != str(start) or any(line.get(k) != v for k, v in check.items()):
                    continue
                data = base64.b64decode(line["data"], validate=True)
                if (
                    len(data)
                    != min(PART_BYTES, row["event_bytes"] - row["part_number"] * PART_BYTES)
                    or line.get("event_digest") != row["event_digest"]
                    or line.get("part_digest") != row["part_digest"]
                    or line.get("event_bytes") != row["event_bytes"]
                    or line.get("seq") != row["source_seq"]
                    or line.get("observed_ms") != row["observed_ms"]
                    or line.get("kind") != row["kind"]
                    or line.get("part_count") != row["part_count"]
                    or hashlib.sha256(data).hexdigest() != row["part_digest"]
                ):
                    raise ValueError
                return data
        return None
    except (httpx.HTTPError, KeyError, ValueError, TypeError, RecursionError):
        raise deny("live_evidence_unavailable", 503) from None


class Verify(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recording_id: CaptureId
    source: LivePage
    event_id: CaptureId
    event_digest: str = Field(pattern="^[0-9a-f]{64}$")
    first: int = Field(ge=0, lt=MAX_OBJECT // PART_BYTES)


def verification_rows(c: Any, body: Verify) -> list[dict[str, Any]]:
    return c.database.execute(
        """select * from browser_live_evidence_part where recording_id=? and tab_id=? and document_id=?
           and event_id=? and event_digest=? and part_number>=? order by part_number limit 8""",
        (
            body.recording_id,
            body.source.tab_id,
            body.source.document_id,
            body.event_id,
            body.event_digest,
            body.first,
        ),
    )
