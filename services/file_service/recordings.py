"""Internal projection storage. Authorization is checked at each object access."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.modules.channel.browser.content import expected_part, job_recording, recording
from app.modules.channel.browser.recordings import MAX_PART_BYTES
from app.modules.identity.application.service_principal import RECORDING_READ, RECORDING_WRITE
from app.shared.exceptions import AppError
from services.file_service.auth import FileWorkerPrincipalVerifier
from services.file_service.internal_http import bearer_token


class RecordingFiles:
    def __init__(self, runtime: Any, storage: Any, verifier: FileWorkerPrincipalVerifier) -> None:
        self.c = runtime
        self.store = storage
        self.verifier = verifier
        self.after = ""

    def routes(self) -> list[Route]:
        return [
            Route(
                "/internal/v1/browser-recordings/{rid}/parts/{number:int}",
                self.put,
                methods=["PUT"],
            ),
            Route("/internal/v1/browser-recordings/evidence", self.get, methods=["POST"]),
        ]

    async def put(self, request: Request) -> JSONResponse:
        rid, n = request.path_params["rid"], request.path_params["number"]

        def target() -> dict[str, Any]:
            rec = recording(self.c, rid)
            part = expected_part(self.c, rid, n)
            self.verifier.verify_recording(
                bearer_token(request),
                RECORDING_WRITE,
                (rec["scope_ref"], rid, str(n), part["sha256"]),
            )
            if rec["state"] != "uploading":
                raise HTTPException(409)
            return part

        try:
            bearer_token(request)
            part = await run_in_threadpool(target)
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > min(MAX_PART_BYTES, part["size_bytes"]):
                    return JSONResponse({}, 413)
                raw.extend(chunk)
            if len(raw) != part["size_bytes"] or hashlib.sha256(raw).hexdigest() != part["sha256"]:
                return JSONResponse({}, 409)

            def write() -> None:
                target()
                self.store.put_recording(rid, n, part["sha256"], bytes(raw))

            await run_in_threadpool(write)
            return JSONResponse({"recording_id": rid, "number": n, "sha256": part["sha256"]})
        except (AppError, HTTPException):
            return JSONResponse({}, 403)

    async def get(self, request: Request) -> JSONResponse:
        try:
            token = bearer_token(request)
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 4096:
                    return JSONResponse({}, 413)
                raw.extend(chunk)
            target = json.loads(raw)
            if not isinstance(target, dict) or set(target) != {
                "job",
                "recording",
                "kind",
                "source",
                "attempt",
            }:
                raise ValueError
            return JSONResponse(
                await run_in_threadpool(self.read, token, target),
                headers={"Cache-Control": "no-store"},
            )
        except (AppError, HTTPException, ValueError, TypeError, KeyError):
            return JSONResponse({}, 403)

    def read(self, token: str, target: dict[str, Any]) -> dict[str, Any]:
        job, rid, kind, source, attempt = (
            target[k] for k in ("job", "recording", "kind", "source", "attempt")
        )
        if (
            any(not isinstance(s, str) for s in (job, rid, kind, source))
            or type(attempt) is not int
        ):
            raise ValueError

        def authorize() -> None:
            rec, current = job_recording(self.c, job, "get_recording_evidence")
            self.verifier.verify_recording(
                token, RECORDING_READ, (rec["scope_ref"], rid, job, str(attempt), kind, source)
            )
            if rec["id"] != rid or current != attempt:
                raise HTTPException(403)

        authorize()
        pos = self.c.database.execute_one(
            """select p.part_number,p.sha256,p.size_bytes,e.line_number
           from browser_recording_evidence e join browser_recording_part p on p.recording_id=e.recording_id and p.part_number=e.part_number
           where e.recording_id=? and e.kind=? and e.source_id=? and p.received_at is not null""",
            (rid, kind, source),
        )
        if not pos:
            raise HTTPException(404)
        key = self.store.recording_key(rid, pos["part_number"], pos["sha256"])
        stream = self.store.open_stream(internal_object_key=key)
        try:
            raw = stream.read(MAX_PART_BYTES + 1)
        finally:
            stream.close()
        if len(raw) != pos["size_bytes"] or hashlib.sha256(raw).hexdigest() != pos["sha256"]:
            raise HTTPException(503)
        row = json.loads(raw.split(b"\n")[pos["line_number"]])
        if (
            row.get("kind") != kind
            or row.get("requestKey" if kind == "request" else "eventId") != source
        ):
            raise HTTPException(409)
        truncated = False
        if len(json.dumps(row, ensure_ascii=False).encode()) > 32 * 1024:
            for name in ("request_details", "response_details", "details"):
                if name in row and len(json.dumps(row[name], ensure_ascii=False).encode()) > 8192:
                    row[name] = {"value": None, "omissions": [{"path": "", "reason": "truncated"}]}
                    if name != "details":
                        row[name.replace("_details", "_fields")] = "partial"
                    truncated = True
            if len(row.get("associations", [])) > 16:
                row["associations"] = row["associations"][:16]
                truncated = True
        authorize()
        return {
            "evidence_id": {"recording_id": rid, "kind": kind, "source_id": source},
            "row": row,
            "truncated": truncated,
        }

    def cleanup(self) -> None:
        # Object writes and metadata commits can fail independently. The exclusive
        # prefix sweep also reclaims writes that finished after an expiry sweep.
        db = self.c.database
        now = int(time.time())
        with db.unit_of_work():
            db.execute(
                """update browser_recording set state=case when state='uploading' then 'upload_expired' else 'expired' end
                          where expires_at<=? and state in ('ready','uploading')""",
                (now,),
            )
            db.execute("""delete from browser_recording_association where recording_id in
                        (select id from browser_recording where state in ('expired','upload_expired'))""")
            db.execute("""delete from browser_recording_part where recording_id in
                        (select id from browser_recording where state in ('expired','upload_expired'))""")
        keys, after = self.store.recording_keys(self.after, 100)
        for key in keys:
            match = re.fullmatch(
                r"browser-recordings/v1/([0-9a-f]{32})/(0|[1-9][0-9]{0,3})/([0-9a-f]{64})", key
            )
            if match:
                rid, n, digest = match.groups()
                live = db.execute_one(
                    """select 1 from browser_recording_part p join browser_recording r on r.id=p.recording_id
                    where r.id=? and p.part_number=? and p.sha256=? and r.expires_at>? and r.state in ('uploading','ready')""",
                    (rid, int(n), digest, now),
                )
                if not live:
                    self.store.delete(internal_object_key=key)
        self.after = after
