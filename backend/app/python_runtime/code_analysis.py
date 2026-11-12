"""Mount lifecycle for code-capable question Jobs; no extraction artifacts or sub-Jobs."""

from pathlib import Path
from typing import Any, Protocol

import httpx

from app.shared.service_identity_client import AccessTokenProvider
from app.shared.knowledge_tool_errors import knowledge_failure
from app.modules.knowledge.domain.code_contracts import CODE_SOURCE_GRANT_PATH, CodeKnowledgeError
from app.modules.knowledge.domain.code_json import parse_json
from app.python_runtime.code_source_mount import CodeSourceMount
from app.python_runtime.job_sandbox import JobSandbox, JobSandboxManager


class GrantClient(Protocol):
    def check(self, binding: dict[str, Any]) -> dict[str, Any]: ...


class CodeGrantClient:
    def __init__(self, tokens: AccessTokenProvider) -> None:
        self.tokens = tokens

    def check(self, binding: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
                with client.stream(
                    "POST",
                    "http://api-server:8000" + CODE_SOURCE_GRANT_PATH,
                    headers={"Authorization": "Bearer " + self.tokens.access_token()},
                    json=binding,
                ) as response:
                    payload = bytearray()
                    for part in response.iter_bytes(chunk_size=8192):
                        if len(payload) + len(part) > 128 * 1024:
                            raise ValueError
                        payload.extend(part)
            value = parse_json(payload.decode())
            if not isinstance(value, dict):
                raise ValueError
            if response.status_code != 200:
                failure = knowledge_failure(value.get("error_code"))
                raise CodeKnowledgeError(
                    failure["code"]
                    if failure["code"] != "knowledge_tool_failed"
                    else "CODE_SOURCE_GRANT_DENIED"
                )
            return value
        except CodeKnowledgeError:
            raise
        except Exception:
            raise CodeKnowledgeError("CODE_SOURCE_GRANT_DENIED") from None


class CodeAnalysisSandboxes(JobSandboxManager):
    def __init__(
        self,
        base: JobSandboxManager,
        request: dict[str, Any],
        *,
        source_root: Path,
        grants: GrantClient,
    ) -> None:
        super().__init__(base.root, limits=base.limits)
        self.capability = request["prompt"]["retrieved_context"]["code_source"]
        self.identity = {key: request[key] for key in ("job_id", "invocation_id", "request_digest")}
        if self.capability.get("contract") != "code-source-capability/v3":
            raise CodeKnowledgeError("CODE_SOURCE_CAPABILITY_CHANGED")
        self.source_root, self.grants = source_root, grants

    def create(self, job_id: str) -> JobSandbox:
        if job_id != self.identity["job_id"] or self.grants.check(self.identity) != self.capability:
            raise CodeKnowledgeError("CODE_SOURCE_CAPABILITY_CHANGED")
        sandbox = super().create(job_id)
        mount = CodeSourceMount(
            root=self.source_root,
            capability=self.capability,
            check=lambda value: self.grants.check({**self.identity, **value}),
        )
        sandbox.source_mount = mount
        mount.start_monitor()
        return sandbox
