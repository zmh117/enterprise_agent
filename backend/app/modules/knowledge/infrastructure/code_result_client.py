"""Control-plane client for one fixed internal response endpoint; no redirects/proxies."""

from collections.abc import Callable
from typing import Any

import httpx

from app.modules.knowledge.domain.code_answers import MAX_RESPONSE_BYTES
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_json import parse_json
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_result_buffer import (
    MAX_DIRECTORY_PREVIEW_BYTES,
    directory_preview,
)
from app.shared.code_result_contract import CODE_RESULT_URL


class CodeResultClient:
    def __init__(self, token: Callable[[], str], *, transport: httpx.BaseTransport | None = None):
        self.token, self.transport = token, transport

    def read(
        self,
        operation_id: str,
        claim: int,
        *,
        result_hash: str,
        remaining: float,
        is_directory_preview: bool = False,
    ) -> dict[str, Any]:
        if not 0 < remaining or type(claim) is not int or claim < 1:
            raise CodeKnowledgeError("CODE_OPERATION_EXPIRED")
        try:
            with httpx.Client(
                transport=self.transport,
                trust_env=False,
                follow_redirects=False,
                timeout=min(10.0, remaining),
            ) as client:
                with client.stream(
                    "POST",
                    CODE_RESULT_URL,
                    headers={"Authorization": "Bearer " + self.token()},
                    json={"operation_id": operation_id, "claim_version": claim},
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise CodeKnowledgeError("CODE_RESULT_DENIED")
                    body = bytearray()
                    for part in response.iter_bytes():
                        limit = (
                            MAX_DIRECTORY_PREVIEW_BYTES
                            if is_directory_preview
                            else MAX_RESPONSE_BYTES
                        )
                        if len(body) + len(part) > limit:
                            raise CodeKnowledgeError("CODE_HISTORY_RESPONSE_TOO_LARGE")
                        body.extend(part)
                    try:
                        value = parse_json(body.decode("utf-8"))
                    except (ValueError, UnicodeError, CodeKnowledgeError):
                        raise CodeKnowledgeError("CODE_RESULT_UNAVAILABLE") from None
                    if response.status_code != 200:
                        code = value.get("error_code") if isinstance(value, dict) else None
                        allowed = {
                            "CODE_RESULT_EXPIRED",
                            "CODE_HISTORY_RESULT_CHANGED",
                            "CODE_RESULT_BUFFER_FULL",
                        }
                        raise CodeKnowledgeError(code if code in allowed else "CODE_RESULT_DENIED")
                    if not isinstance(value, dict) or digest(value) != result_hash:
                        raise CodeKnowledgeError("CODE_HISTORY_RESULT_CHANGED")
                    if is_directory_preview and not directory_preview(value):
                        raise CodeKnowledgeError("CODE_RESULT_INVALID")
                    return value
        except CodeKnowledgeError:
            raise
        except Exception:
            raise CodeKnowledgeError("CODE_RESULT_UNAVAILABLE") from None
