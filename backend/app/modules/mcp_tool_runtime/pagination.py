from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from app.shared.exceptions import ToolPolicyError

from .contracts import ToolRequestContext


class ToolPaginationCursorCodec:
    """Issue bounded cursors bound to one Job Tool contract and authorization snapshot."""

    VERSION = 1
    MAX_CURSOR_CHARS = 4096

    @classmethod
    def fingerprint(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value).encode()).hexdigest()

    @classmethod
    def encode(
        cls,
        *,
        context: ToolRequestContext,
        purpose: str,
        request: dict[str, Any],
        state_fingerprint: str,
        position: Any,
    ) -> str:
        payload = {
            "v": cls.VERSION,
            "purpose": purpose,
            "request_hash": cls.fingerprint(request),
            "state_fingerprint": cls._digest(state_fingerprint),
            "position": position,
        }
        body = cls._canonical(payload)
        envelope = {
            "payload": payload,
            "checksum": hashlib.sha256(
                f"{body}|{cls._context_material(context)}".encode()
            ).hexdigest(),
        }
        encoded = base64.urlsafe_b64encode(cls._canonical(envelope).encode()).rstrip(b"=")
        cursor = encoded.decode()
        if len(cursor) > cls.MAX_CURSOR_CHARS:
            raise cls._invalid("Pagination cursor exceeds the response limit")
        return cursor

    @classmethod
    def decode(
        cls,
        cursor: str,
        *,
        context: ToolRequestContext,
        purpose: str,
        request: dict[str, Any],
        state_fingerprint: str,
    ) -> Any:
        if not cursor or len(cursor) > cls.MAX_CURSOR_CHARS:
            raise cls._invalid("Pagination cursor is missing or too large")
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or set(envelope) != {"payload", "checksum"}:
                raise ValueError("cursor envelope invalid")
            payload = envelope["payload"]
            if not isinstance(payload, dict) or set(payload) != {
                "v",
                "purpose",
                "request_hash",
                "state_fingerprint",
                "position",
            }:
                raise ValueError("cursor payload invalid")
            body = cls._canonical(payload)
            expected = hashlib.sha256(
                f"{body}|{cls._context_material(context)}".encode()
            ).hexdigest()
            if not hmac.compare_digest(str(envelope["checksum"]), expected):
                raise ValueError("cursor checksum invalid")
            if payload["v"] != cls.VERSION or str(payload["purpose"]) != purpose:
                raise ValueError("cursor purpose invalid")
            if not hmac.compare_digest(
                str(payload["request_hash"]),
                cls.fingerprint(request),
            ):
                raise ValueError("cursor request binding invalid")
            if not hmac.compare_digest(
                str(payload["state_fingerprint"]),
                cls._digest(state_fingerprint),
            ):
                raise cls._stale()
            return payload["position"]
        except ToolPolicyError:
            raise
        except (UnicodeDecodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise cls._invalid("Pagination cursor is invalid") from exc

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _digest(value: str) -> str:
        text = str(value or "")
        if len(text) == 64 and all(character in "0123456789abcdef" for character in text.lower()):
            return text.lower()
        return hashlib.sha256(text.encode()).hexdigest()

    @classmethod
    def _context_material(cls, context: ToolRequestContext) -> str:
        return cls.fingerprint(
            {
                "job_id": context.job_id,
                "user_id": context.user_id,
                "application_id": context.application_id,
                "snapshot_hash": context.snapshot_hash,
                "authorization_hash": context.authorization_hash,
            }
        )

    @staticmethod
    def _invalid(message: str) -> ToolPolicyError:
        return ToolPolicyError(
            message,
            safe_message="分页游标无效，请从第一页重新查询",
            error_code="mcp_pagination_cursor_invalid",
        )

    @staticmethod
    def _stale() -> ToolPolicyError:
        return ToolPolicyError(
            "Pagination cursor state is stale",
            safe_message="分页期间资源或授权已变化，请从第一页重新查询",
            error_code="mcp_pagination_cursor_stale",
        )
