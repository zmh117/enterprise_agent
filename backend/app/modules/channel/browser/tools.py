"""Read-only recording tools executed in the current Job's tool-mcp context."""

from __future__ import annotations

import base64
import hmac
import json
from typing import Any

from fastapi import HTTPException

from app.modules.channel.browser.content import job_recording
from app.modules.channel.browser.file_client import internal_request
from app.modules.channel.browser.recordings import contract
from app.modules.mcp_tool_runtime.contracts import ToolResult
from app.shared.exceptions import ToolPolicyError
from app.shared.service_identity_client import ServicePrincipalTokenClient


class RecordingTools:
    def __init__(self, c: Any) -> None:
        self.c = c
        cfg = c.settings.service_principal
        self.identity = (
            ServicePrincipalTokenClient(
                base_url=cfg.identity_base_url,
                allowed_hosts=cfg.identity_allowed_hosts,
                bootstrap_credential_file=cfg.recording_tool_bootstrap_token_file,
                timeout_seconds=cfg.timeout_seconds,
                refresh_skew_seconds=cfg.refresh_skew_seconds,
            )
            if cfg.recording_tool_bootstrap_token_file
            else None
        )

    def call(self, name: str, job: str, args: dict[str, Any]) -> ToolResult:
        try:
            if self.c.database.execute_one(
                "select 1 from browser_live_job_page where job_id=?", (job,)
            ):
                from app.modules.channel.browser.live_query import authorized_job

                scope = authorized_job(self.c, job, name)
                if not self.identity or not (
                    set(args) == {"live"} or (not args and name == "search_recording")
                ):
                    raise ValueError
                inputs = args.get("live", {})
                if not contract(
                    "LiveSearch" if name == "search_recording" else "LiveDetail"
                ).is_valid(inputs):
                    raise ValueError
                cfg = self.c.settings.service_principal
                result = internal_request(
                    cfg.identity_base_url,
                    cfg.identity_allowed_hosts,
                    "/api/internal/service-principal/recording-evidence",
                    self.identity.access_token(),
                    body=json.dumps(
                        {
                            "job": job,
                            "attempt": scope["retry_count"],
                            "live_tool": name,
                            "arguments": inputs,
                        }
                    ).encode(),
                    media="application/json",
                    timeout=self.c.settings.file_service.internal_timeout_seconds,
                )
                if authorized_job(self.c, job, name) != scope or "coverage" not in result:
                    raise ValueError
                return ToolResult(result, {}, truncated=bool(result["truncated"]))
            rec, attempt = job_recording(self.c, job, name)
            if name == "search_recording" and contract("SearchRecording").is_valid(args):
                result = self.search(job, rec, args)
            elif name == "get_recording_evidence" and contract("GetRecordingEvidence").is_valid(
                args
            ):
                if args["evidence_id"]["recording_id"] != rec["id"] or not self.identity:
                    raise ValueError
                cfg = self.c.settings.service_principal
                result = internal_request(
                    cfg.identity_base_url,
                    cfg.identity_allowed_hosts,
                    "/api/internal/service-principal/recording-evidence",
                    self.identity.access_token(),
                    body=json.dumps({"job": job, "attempt": attempt, **args}).encode(),
                    media="application/json",
                    timeout=self.c.settings.file_service.internal_timeout_seconds,
                )
                if result.get("evidence_id") != args["evidence_id"] or not contract(
                    "EvidenceResult"
                ).is_valid(result):
                    raise ValueError
            else:
                raise ValueError
            final, current = job_recording(self.c, job, name)
            if final["id"] != rec["id"] or current != attempt:
                raise ValueError
            return ToolResult(result, {}, truncated=bool(result["truncated"]))
        except (HTTPException, ValueError, TypeError, KeyError, RecursionError):
            raise ToolPolicyError(
                "Recording evidence unavailable",
                safe_message="录制或本次查询不可用，请检查证据范围和权限",
                error_code="recording_query_denied",
            ) from None

    def search(self, job: str, rec: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        if args.get("from_ms", 0) > args.get("to_ms", 9007199254740991):
            raise ValueError
        where = ["e.recording_id=?"]
        values: list[Any] = [rec["id"]]
        for col in ("kind", "path_template", "method", "http_status", "business_outcome", "action"):
            if col in args:
                where.append(f"e.{col}=?")
                values.append(args[col])
        for col, op in (("from_ms", ">="), ("to_ms", "<=")):
            if col in args:
                where.append("e.offset_ms" + op + "?")
                values.append(args[col])
        basis = "null"
        basis_args: list[Any] = []
        if related := args.get("related_to"):
            if related["recording_id"] != rec["id"]:
                raise ValueError
            other, own, kind = (
                ("request_key", "action_id", "action")
                if related["kind"] == "request"
                else ("action_id", "request_key", "request")
            )
            link = f"from browser_recording_association a where a.recording_id=e.recording_id and a.{own}=e.source_id and a.{other}=?"
            where.extend(["e.kind=?", "exists(select 1 " + link + ")"])
            values.extend([kind, related["source_id"]])
            basis = "(select min(a.basis) " + link + ")"
            basis_args.append(related["source_id"])
        filters = {k: v for k, v in args.items() if k not in {"cursor", "limit"}}
        root = self.c.settings.app_config_master_key
        if not root:
            raise ValueError
        key = hmac.digest(
            root.encode(),
            json.dumps(
                ["recording-cursor-v1", job, rec["id"], rec["scope_ref"], filters], sort_keys=True
            ).encode(),
            "sha256",
        )
        if encoded := args.get("cursor"):
            value = base64.b64decode(encoded, altchars=b"-_", validate=True)
            if len(value) < 33 or not hmac.compare_digest(
                value[:32], hmac.digest(key, value[32:], "sha256")
            ):
                raise ValueError
            offset, kind, source = json.loads(value[32:])
            where.append("(e.offset_ms,e.kind,e.source_id)>(?,?,?)")
            values.extend([offset, kind, source])
        limit = args.get("limit", 25)
        rows = self.c.database.execute(
            "select e.*, "
            + basis
            + " as association_basis from browser_recording_evidence e where "
            + " and ".join(where)
            + " order by e.offset_ms,e.kind,e.source_id limit ?",
            (*basis_args, *values, limit + 1),
        )
        candidates = [
            {
                "evidence_id": {
                    "recording_id": rec["id"],
                    "kind": r["kind"],
                    "source_id": r["source_id"],
                },
                **{
                    k: r[k]
                    for k in (
                        "offset_ms",
                        "method",
                        "path_template",
                        "http_status",
                        "business_outcome",
                        "action",
                        "association_basis",
                    )
                    if r[k] is not None
                },
            }
            for r in rows[:limit]
        ]
        coverage = json.loads(rec["coverage_json"])
        size = len(json.dumps(coverage).encode()) + 2048  # Envelope and signed cursor.
        hits: list[dict[str, Any]] = []
        for candidate in candidates:
            size += len(json.dumps(candidate, separators=(",", ":")).encode()) + 1
            if size > 32 * 1024 and hits:
                break
            hits.append(candidate)
        cursor = None
        if len(rows) > len(hits):
            last = rows[len(hits) - 1]
            pos = json.dumps(
                [last["offset_ms"], last["kind"], last["source_id"]], separators=(",", ":")
            ).encode()
            cursor = base64.urlsafe_b64encode(hmac.digest(key, pos, "sha256") + pos).decode()
        return {
            "coverage": coverage,
            "hits": hits,
            "truncated": bool(cursor),
            "next_cursor": cursor,
        }
