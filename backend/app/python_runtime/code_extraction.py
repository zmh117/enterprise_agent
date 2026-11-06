"""Runtime mount and artifact lifecycle for a server-bound extraction invocation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import httpx

from app.shared.service_identity_client import AccessTokenProvider
from app.modules.knowledge.domain.code_contracts import CODE_SOURCE_GRANT_PATH
from app.modules.knowledge.domain.code_contracts import (
    CodeKnowledgeError,
    AUTHORING,
    MAX_PACKAGE_BYTES,
)
from app.modules.knowledge.domain.code_package import parse_json
from app.modules.knowledge.domain.normalization import canonical_json
from app.modules.knowledge.infrastructure.code_source import _read_beneath
from app.modules.knowledge.infrastructure.code_artifact_directory import CodeArtifactDirectory
from app.python_runtime.code_candidate import seal_candidate
from app.python_runtime.code_source_mount import CodeSourceMount
from app.python_runtime.job_sandbox import JobSandbox, JobSandboxManager


class GrantClient(Protocol):
    def check(self, binding: dict[str, str]) -> dict[str, Any]: ...


class CodeGrantClient:
    def __init__(self, tokens: AccessTokenProvider) -> None:
        self.tokens = tokens

    def check(self, binding: dict[str, str]) -> dict[str, Any]:
        try:
            # Deployment-fixed internal endpoint. No redirects, proxies, model URLs or cookies.
            with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
                with client.stream(
                    "POST",
                    "http://api-server:8000" + CODE_SOURCE_GRANT_PATH,
                    headers={"Authorization": "Bearer " + self.tokens.access_token()},
                    json=binding,
                ) as response:
                    if response.status_code != 200:
                        raise ValueError
                    payload = bytearray()
                    for part in response.iter_bytes(chunk_size=8192):
                        if len(payload) + len(part) > 128 * 1024:
                            raise ValueError
                        payload.extend(part)
            value = parse_json(payload.decode())
            if not isinstance(value, dict):
                raise ValueError
            return value
        except Exception:
            raise CodeKnowledgeError("code_source_grant_denied") from None


class CodeExtractionSandboxes(JobSandboxManager):
    def __init__(
        self,
        base: JobSandboxManager,
        request: dict[str, Any],
        *,
        source_root: Path,
        artifact_root: Path,
        grants: GrantClient,
    ) -> None:
        super().__init__(base.root, limits=base.limits)
        self.grant = request["prompt"]["retrieved_context"]["code_source"]
        self.identity = {
            name: request[name] for name in ("job_id", "invocation_id", "request_digest")
        }
        if (
            request["mcp_servers"]
            or "extract-business-knowledge" not in request["prompt"]["skills"]
        ):
            raise CodeKnowledgeError("code_extraction_tools_invalid")
        self.grants = grants
        self.source_root = source_root
        self.artifacts = CodeArtifactDirectory(artifact_root)

    def _recheck(self) -> None:
        if self.grants.check(self.identity) != self.grant:
            raise CodeKnowledgeError("code_source_grant_changed")

    def create(self, job_id: str) -> JobSandbox:
        if job_id != self.identity["job_id"]:
            raise CodeKnowledgeError("code_source_job_mismatch")
        mount = CodeSourceMount(
            root=self.source_root,
            snapshot_id=self.grant["candidate_manifest"]["source_snapshot_id"],
            manifest_hash=self.grant["manifest_hash"],
            allowed_prefixes=tuple(self.grant["allowed_prefixes"]),
            recheck=self._recheck,
        )
        sandbox = super().create(job_id)
        sandbox.source_mount = mount
        contract = sandbox.path / "inputs/code-contract.txt"
        contract.write_text(
            canonical_json(
                {
                    "schema": AUTHORING,
                    "fixed_manifest": self.grant["candidate_manifest"],
                    "identity_catalog": self.grant["identity_catalog"],
                    "known_states": self.grant["scope"].get("known_states", []),
                    "instructions": "Write one JSON object matching schema to outputs/candidate.txt. "
                    "Set every excerpt_hash to null; Runtime calculates checksums from verified evidence lines.",
                    "source_access": {
                        "read_root": str(mount.root),
                        "virtual_root": "source/",
                        "read_fields": ["file_path", "offset", "limit"],
                        "read_max_lines": 400,
                        "search_fields": ["path", "pattern"],
                        "grep_file_content": "For an exact source file, output_mode=content returns "
                        "up to 40 numbered matches. Then Read the relevant function context.",
                        "navigation": "Use read_root + '/' + scope-relative paths for Read/Grep/Glob. "
                        "Grep/Glob validate physical paths before authorization hooks; the virtual "
                        "source/ alias is supported only for Read. All access still requires the "
                        "current Job's exact snapshot and allowed prefixes.",
                    },
                }
            ),
            encoding="utf-8",
        )
        contract.chmod(0o444)
        return sandbox

    def finish(self, sandbox: JobSandbox) -> None:
        self._recheck()
        if not isinstance(sandbox.source_mount, CodeSourceMount):
            raise CodeKnowledgeError("code_mount_unavailable")
        raw = _read_beneath(sandbox.path, "outputs/candidate.txt", MAX_PACKAGE_BYTES)
        sealed = seal_candidate(
            raw,
            sandbox.source_mount,
            self.grant["candidate_manifest"],
            expected_entries=set(self.grant["scope"]["entry_ids"]),
            known_states=self.grant["scope"].get("known_states", []),
        )
        self._recheck()
        self.artifacts.publish(
            sandbox.path,
            {**self.identity, "grant": self.grant},
            sealed_candidate=sealed,
        )
