from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from app.modules.identity.application.service_principal import ServicePrincipalTokenError


async def read_recording_evidence(request: Request) -> JSONResponse:
    import json
    from starlette.concurrency import run_in_threadpool
    from app.modules.channel.browser.content import job_recording
    from app.modules.channel.browser.file_client import internal_request
    from app.modules.channel.browser.recordings import contract
    from app.modules.identity.application.principal_jwt import PrincipalJwks
    from app.modules.identity.application.service_principal import RecordingToolVerifier

    c = request.app.state.container
    issuer = c.service_principal_token_issuer
    if not issuer:
        raise HTTPException(503)
    headers = request.headers.getlist("authorization")
    if len(headers) != 1 or not headers[0].startswith("Bearer "):
        raise HTTPException(401)
    verifier = RecordingToolVerifier(PrincipalJwks.from_dict(issuer.signing_key.public_jwks()))
    try:
        verifier.verify(headers[0][7:])
    except ServicePrincipalTokenError:
        raise HTTPException(403) from None
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 4096:
            raise HTTPException(413)
        raw.extend(chunk)

    def read() -> dict[str, Any]:
        try:
            value = json.loads(raw)
            if isinstance(value, dict) and set(value) == {
                "job",
                "attempt",
                "live_tool",
                "arguments",
            }:
                from app.modules.channel.browser import live_query

                if (
                    not isinstance(value["job"], str)
                    or len(value["job"]) > 128
                    or type(value["attempt"]) is not int
                    or not isinstance(value["arguments"], dict)
                ):
                    raise ValueError
                return live_query.run(
                    c, value["job"], value["attempt"], value["live_tool"], value["arguments"]
                )
            if (
                not isinstance(value, dict)
                or set(value) != {"job", "attempt", "evidence_id"}
                or not contract("EvidenceId").is_valid(value["evidence_id"])
            ):
                raise ValueError
            evidence = value["evidence_id"]
            job = value["job"]
            if not isinstance(job, str) or len(job) > 128 or type(value["attempt"]) is not int:
                raise ValueError
        except (ValueError, TypeError, RecursionError):
            raise HTTPException(422) from None
        rec, attempt = job_recording(c, job, "get_recording_evidence")
        if rec["id"] != evidence["recording_id"] or attempt != value["attempt"]:
            raise HTTPException(403)
        source, kind = evidence["source_id"], evidence["kind"]
        if not c.database.execute_one(
            "select 1 from browser_recording_evidence where recording_id=? and kind=? and source_id=?",
            (rec["id"], kind, source),
        ):
            raise HTTPException(404)
        target = {
            "job": job,
            "attempt": attempt,
            "recording": rec["id"],
            "kind": kind,
            "source": source,
        }
        token = issuer.recording_read(scope=rec["scope_ref"], **target)
        cfg = c.settings.file_service
        return internal_request(
            cfg.internal_base_url,
            cfg.internal_allowed_hosts,
            "/internal/v1/browser-recordings/evidence",
            token,
            body=json.dumps(target).encode(),
            media="application/json",
            timeout=cfg.internal_timeout_seconds,
        )

    return JSONResponse(await run_in_threadpool(read), headers={"Cache-Control": "no-store"})
