"""Original-Job readonly checkout guard and bounded, host-observed file evidence."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, TYPE_CHECKING
from threading import Event, Thread
from app.modules.knowledge.domain.normalization import digest
from app.python_runtime.file_mcp_bridge import safe_meta

from app.modules.knowledge.domain.code_answers import code_path
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.python_runtime.code_checkout_reader import CodeCheckoutReader
from app.python_runtime.code_source_search import SourceSearchBatch, search_options

if TYPE_CHECKING:
    from app.python_runtime.job_sandbox import JobSandbox


class CodeSourceMount:
    def __init__(
        self,
        *,
        root: Path,
        capability: dict[str, Any],
        check: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        if not root.is_absolute() or root.resolve(strict=True) != root:
            raise CodeKnowledgeError("CODE_CHECKOUT_ROOT_INVALID")
        self.volume_root, self.capability, self.check = root, capability, check
        self.grant: dict[str, Any] | None = None
        self.reader: CodeCheckoutReader | None = None
        self.pending: dict[str, dict[str, Any]] = {}
        self.tool_denials: dict[str, str] = {}
        self.condition = asyncio.Condition()
        self.closing = False
        self.saved_analysis_id: str | None = None
        self._stop = Event()
        self._monitor: Thread | None = None
        self.sandbox: JobSandbox | None = None
        self.search_lock = asyncio.Lock()
        self.searches: dict[str, SourceSearchBatch] = {}

    def start_monitor(self) -> None:
        def heartbeat() -> None:
            while not self._stop.wait(5):
                if self.grant is not None:
                    try:
                        self.check(
                            {"action": "heartbeat", "analysis_id": self.grant["analysis_id"]}
                        )
                    except Exception:
                        self.closing = True
                        return

        self._monitor = Thread(target=heartbeat, name="code-read-lease", daemon=True)
        self._monitor.start()

    def record_denial(self, call_id: str, code: str) -> None:
        from app.python_runtime.code_tool_errors import code_tool_failure

        if call_id:
            self.tool_denials[call_id] = code_tool_failure(code)["code"]

    def apply_denials(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            if event.get("status") == "FAILED":
                code = self.tool_denials.pop(event["tool_call_id"], None)
                if code:
                    event.update(status="DENIED", error_code=code)

    def close(self) -> None:
        # Actual release is owned by the worker after invocation quiescence.
        self.closing = True
        self._stop.set()
        if self._monitor is not None:
            self._monitor.join(timeout=6)

    @property
    def root(self) -> Path:
        if self.reader is None:
            raise CodeKnowledgeError("CODE_READ_GRANT_REQUIRED")
        return self.reader.root

    def _recheck(self) -> dict[str, Any]:
        if self.grant is None:
            raise CodeKnowledgeError("CODE_READ_GRANT_REQUIRED")
        observed = self.check({"action": "grant", "analysis_id": self.grant["analysis_id"]})
        if observed != self.grant:
            raise CodeKnowledgeError("CODE_SOURCE_GRANT_CHANGED")
        return observed

    def authorize(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:  # noqa: C901
        """Synchronous sandbox adapter; PreToolUse also tracks the actual call id."""
        field = "path" if tool in {"Glob", "Grep"} else "file_path"
        if not self.owns_path(arguments.get(field)):
            return None
        if tool not in {"Read", "Glob", "Grep"}:
            raise CodeKnowledgeError("CODE_SOURCE_WRITE_DENIED")
        if self.closing:
            raise CodeKnowledgeError("CODE_SOURCE_READS_CLOSED")
        self._recheck()
        assert self.reader is not None
        field = "file_path" if tool == "Read" else "path"
        value = arguments.get(field)
        if not isinstance(value, str):
            raise CodeKnowledgeError("CODE_SOURCE_PATH_DENIED")
        if value == "source":
            path = ""
        elif value.startswith("source/"):
            path = value.removeprefix("source/")
        elif value == str(self.root):
            path = ""
        elif value.startswith(str(self.root) + "/"):
            path = value[len(str(self.root)) + 1 :]
        else:
            raise CodeKnowledgeError("CODE_SOURCE_PATH_DENIED")
        path = code_path(path, root=tool in {"Glob", "Grep"})
        if tool == "Read":
            if set(arguments) - {"file_path", "offset", "limit"}:
                raise CodeKnowledgeError("CODE_SOURCE_READ_INVALID")
            start, limit = arguments.get("offset", 1), arguments.get("limit", 400)
            self.reader.read(path, start, limit)
            return {"file_path": str(self.root / path), "offset": start, "limit": limit}
        if tool == "Grep":
            return search_options(arguments) | {"path": path}
        if set(arguments) - {"path", "pattern", "output_mode"}:
            raise CodeKnowledgeError("CODE_SOURCE_SEARCH_INVALID")
        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not 1 <= len(pattern) <= 1024:
            raise CodeKnowledgeError("CODE_SOURCE_SEARCH_INVALID")
        if (
            pattern.startswith(("/", "-"))
            or "\\" in pattern
            or ".." in pattern.split("/")
            or ".svn" in pattern.casefold()
            or "\x00" in pattern
        ):
            raise CodeKnowledgeError("CODE_SOURCE_SEARCH_INVALID")
        if not path:
            # Never let the native glob walk the working-copy metadata root.
            prefix, sep, tail = pattern.partition("/")
            if not sep or any(c in prefix for c in "*?[]{}"):
                raise CodeKnowledgeError("CODE_SOURCE_GLOB_DIRECTORY_REQUIRED")
            path, pattern = code_path(prefix), tail
        self.reader.tracked(path, directory=True)
        return {"path": str(self.root / path), "pattern": pattern}

    def owns_path(self, value: Any) -> bool:
        return isinstance(value, str) and (
            value == "source"
            or value.startswith("source/")
            or value == str(self.volume_root)
            or value.startswith(str(self.volume_root) + "/")
        )

    async def before_native(self, name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
        if not isinstance(call_id, str) or not call_id:
            raise CodeKnowledgeError("CODE_SOURCE_CALL_ID_REQUIRED")
        async with self.condition:
            if self.closing or call_id in self.pending or len(self.pending) >= 4:
                raise CodeKnowledgeError("CODE_SOURCE_READS_CLOSED")
            self.pending[call_id] = {"tool": name}
        try:
            authorized = await asyncio.to_thread(self.authorize, name, args)
            if authorized is None:
                raise CodeKnowledgeError("CODE_SOURCE_PATH_DENIED")
            observed: dict[str, Any] = {"tool": name, "arguments": authorized}
            if name == "Grep":
                authorized = await self._prepare_search(authorized, call_id)
            if name == "Read":
                assert self.reader is not None
                path = str(Path(authorized["file_path"]).relative_to(self.root))
                observed.update(
                    path=path,
                    data=await asyncio.to_thread(
                        self.reader.read,
                        path,
                        authorized["offset"],
                        authorized["limit"],
                    ),
                )
            async with self.condition:
                self.pending[call_id] = observed
            return authorized
        except BaseException:
            await self.failed(call_id)
            raise

    async def failed(self, call_id: str) -> None:
        batch = self.searches.pop(call_id, None)
        if batch is not None:
            try:
                batch.close()
            finally:
                self.search_lock.release()
        async with self.condition:
            self.pending.pop(call_id, None)
            self.condition.notify_all()

    async def _prepare_search(self, args: dict[str, Any], call_id: str) -> dict[str, Any]:
        if self.sandbox is None or self.reader is None:
            raise CodeKnowledgeError("CODE_SOURCE_SEARCH_UNAVAILABLE")
        await self.search_lock.acquire()
        batch = SourceSearchBatch(self.sandbox, self.reader, args)
        self.searches[call_id] = batch
        # Cancellation must not delete a cache while its preparation thread writes it.
        task = asyncio.create_task(asyncio.to_thread(batch.prepare, args["path"]))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except Exception:
                pass
            raise

    async def after_native(self, call_id: str, response: Any) -> dict[str, Any]:
        observed = self.pending.get(call_id)
        if observed is None:
            raise CodeKnowledgeError("CODE_SOURCE_CALL_ID_REQUIRED")
        try:
            await asyncio.to_thread(self._recheck)
            assert self.reader is not None and self.grant is not None
            name = observed["tool"]
            if name == "Grep":
                self.reader.identity.check()
                return self.searches[call_id].render(response)
            if name == "Read":
                # Only the real SDK text-Read output structure is accepted. A shape
                # mismatch raises and is blocked by the fail-closed PostToolUse hook.
                if (
                    not isinstance(response, dict)
                    or response.get("type") != "text"
                    or not isinstance(response.get("file"), dict)
                    or not {"filePath", "content", "numLines", "startLine", "totalLines"}
                    <= response["file"].keys()
                ):
                    raise CodeKnowledgeError("CODE_SOURCE_READ_OUTPUT_UNSUPPORTED")
                args = observed["arguments"]
                data = await asyncio.to_thread(
                    self.reader.read, observed["path"], args["offset"], args["limit"]
                )
                if data != observed["data"]:
                    raise CodeKnowledgeError("CODE_CHECKOUT_CHANGED")
                proof = {k: v for k, v in data.items() if k != "text"}
                proof.update(kind="file_read", relative_path=observed["path"], tool_call_id=call_id)
                recorded = await asyncio.to_thread(
                    self.check,
                    {
                        "action": "evidence",
                        "analysis_id": self.grant["analysis_id"],
                        "evidence": proof,
                    },
                )
                updated = deepcopy(response)
                updated["file"].update(
                    content=data["text"],
                    filePath=args["file_path"],
                    numLines=data["line_end"] - data["line_start"] + 1,
                    startLine=data["line_start"],
                )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "updatedToolOutput": updated,
                        "additionalContext": "Host verified source evidence: "
                        + recorded["evidence_id"]
                        + "; SVN r"
                        + str(recorded["svn_revision"])
                        + "; lines "
                        + str(data["line_start"])
                        + "-"
                        + str(data["line_end"]),
                    }
                }
            # Search output contains only authorized tracked filenames, no excerpts.
            if not isinstance(response, dict) or not isinstance(response.get("filenames"), list):
                raise CodeKnowledgeError("CODE_SOURCE_SEARCH_OUTPUT_UNSUPPORTED")
            if len(response["filenames"]) > 100:
                raise CodeKnowledgeError("CODE_SOURCE_SEARCH_LIMIT")
            for path in response["filenames"]:
                if not isinstance(path, str) or not path.startswith(str(self.root) + "/"):
                    raise CodeKnowledgeError("CODE_SOURCE_PATH_DENIED")
                await asyncio.to_thread(self.reader.tracked, path[len(str(self.root)) + 1 :])
            return {}
        finally:
            await self.failed(call_id)

    async def before_mcp(self, name: str, arguments: dict[str, Any]) -> None:
        if name != "knowledge_save_code_answer":
            return
        async with self.condition:
            if self.grant is None and self.saved_analysis_id == arguments["analysis_id"]:
                return
            if self.grant is None or self.grant["analysis_id"] != arguments["analysis_id"]:
                raise CodeKnowledgeError("CODE_ANALYSIS_MISMATCH")
            self.closing = True
            await self.condition.wait_for(lambda: not self.pending)
        while True:
            result = await asyncio.to_thread(
                self.check, {"action": "quiesce", "analysis_id": arguments["analysis_id"]}
            )
            if result.get("state") != "draining":
                break
            await asyncio.sleep(0.1)

    async def after_mcp(self, name: str, result: Any) -> Any:
        if result.is_error or not isinstance(result.structured_content, dict):
            return result
        value = result.structured_content
        access = value.get("source_access")
        if isinstance(access, dict):
            grant = await asyncio.to_thread(
                self.check, {"action": "grant", "analysis_id": access["analysis_id"]}
            )
            if grant["capability_hash"] != self.capability["capability_hash"]:
                raise CodeKnowledgeError("CODE_SOURCE_CAPABILITY_CHANGED")
            if any(
                access[k] != grant[k]
                for k in (
                    "analysis_id",
                    "source_id",
                    "checkout_id",
                    "revision",
                    "generation",
                    "directory",
                    "allowed_paths",
                )
            ):
                raise CodeKnowledgeError("CODE_SOURCE_GRANT_CHANGED")
            self.reader = CodeCheckoutReader(self.volume_root, grant)
            self.grant, self.closing = grant, False
            # Tell the model the container-local root after host validation.
            value["source_access"] = {**access, "directory": str(self.reader.root)}
        if (
            self.grant is not None
            and value.get("state") == "succeeded"
            and value.get("operation_kind") in {"log", "diff", "blame"}
            and "result" in value
        ):
            metadata = safe_meta(result) or {}
            tool_call_id = metadata.get("enterprise-agent/agent-tool-call-id")
            if not isinstance(tool_call_id, str):
                raise CodeKnowledgeError("CODE_EVIDENCE_UNVERIFIED")
            proof = await asyncio.to_thread(
                self.check,
                {
                    "action": "evidence",
                    "analysis_id": self.grant["analysis_id"],
                    "evidence": {
                        "kind": "svn_history",
                        "operation_id": value["operation_id"],
                        "result_hash": digest(value["result"]),
                        "tool_call_id": tool_call_id,
                    },
                },
            )
            value["evidence_id"] = proof["evidence_id"]
        if name == "knowledge_save_code_answer" and value.get("saved"):
            self.saved_analysis_id = value["analysis_id"]
            self.grant = None
            self.reader = None
        return result
