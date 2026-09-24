"""单轮 ONES 知识同步：从持久阶段恢复，绝不在候选未就绪时发布。"""

from collections.abc import Callable
from typing import Any, Protocol

from app.modules.knowledge.domain.chunking import (
    DEFAULT_PROFILE,
    KEEP_IDS_PROFILE,
    WORK_ITEM_PROFILE,
    ChunkProfile,
)
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.vector_contract import VectorError


class ManagedPipelineStore(Protocol):
    def binding(self, binding_id: str) -> dict[str, Any]: ...
    def active_collection(self, binding_id: str) -> dict[str, Any] | None: ...
    def run(self, run_id: str, *, lock: bool = False) -> dict[str, Any]: ...
    def assert_configuration(
        self, run: dict[str, Any], *, lock: bool = False
    ) -> dict[str, Any]: ...
    def changed_bases(self, run_id: str) -> set[str]: ...
    def advance(self, run_id: str, *, expected_phase: str, phase: str) -> None: ...
    def fail(self, run_id: str, code: str) -> None: ...
    def summary(self, run_id: str) -> dict[str, Any]: ...


def _profile(binding: dict[str, Any], base_id: str) -> ChunkProfile:
    pins = [
        item
        for item in binding["resource_pins_json"].values()
        if item["knowledge_base_id"] == base_id
    ]
    if not pins:
        return WORK_ITEM_PROFILE
    known = {
        profile.fingerprint: profile
        for profile in (DEFAULT_PROFILE, WORK_ITEM_PROFILE, KEEP_IDS_PROFILE)
    }
    hashes = {item["chunk_profile_hash"] for item in pins}
    if len(hashes) != 1 or next(iter(hashes)) not in known:
        raise ExportValidationError("knowledge_sync_resource_profile_changed")
    return known[next(iter(hashes))]


class ManagedSyncPipeline:
    def __init__(
        self,
        repository: ManagedPipelineStore,
        *,
        collect_once: Callable[[str], dict[str, Any]],
        chunk_base: Callable[[str, str, ChunkProfile], None],
        index_base: Callable[[str, str, ChunkProfile], None],
        activate: Callable[[str], dict[str, Any]],
    ) -> None:
        self.repository = repository
        self.collect_once = collect_once
        self.chunk_base = chunk_base
        self.index_base = index_base
        self.activate = activate

    def run_once(self, binding_id: str) -> dict[str, Any]:
        repo = self.repository
        binding = repo.binding(binding_id)
        if binding["enabled"] != 1:
            raise ExportValidationError("knowledge_collection_disabled")
        active = repo.active_collection(binding_id)
        run_id: str | None = active["id"] if active else None
        try:
            if active is None or active["phase"] == "COLLECTING":
                result = self.collect_once(binding_id)
                run_id = result["run_id"]
            assert run_id is not None
            run = repo.run(run_id)
            binding = repo.assert_configuration(run)
            if run["phase"] == "STAGED":
                repo.advance(run_id, expected_phase="STAGED", phase="CHUNKING")
                run = repo.run(run_id)
            changed = repo.changed_bases(run_id)
            codes = {
                stable_id("base", code): code
                for code in binding["configuration_json"]["base_codes"].values()
            }
            if not changed <= set(codes):
                raise ExportValidationError("knowledge_sync_candidate_conflict")
            if run["phase"] == "CHUNKING":
                for base_id in sorted(changed):
                    repo.assert_configuration(repo.run(run_id))
                    self.chunk_base(run_id, codes[base_id], _profile(binding, base_id))
                repo.advance(run_id, expected_phase="CHUNKING", phase="INDEXING")
                run = repo.run(run_id)
            if run["phase"] == "INDEXING":
                for base_id in sorted(changed):
                    repo.assert_configuration(repo.run(run_id))
                    self.index_base(run_id, codes[base_id], _profile(binding, base_id))
                run = repo.run(run_id)
            if run["phase"] not in {"INDEXING", "VERIFIED"}:
                raise ExportValidationError("knowledge_sync_phase_invalid")
            repo.assert_configuration(run)
            return self.activate(run_id)
        except Exception as exc:
            if run_id is not None:
                repo.fail(
                    run_id,
                    exc.code
                    if isinstance(exc, (ExportValidationError, VectorError))
                    else "knowledge_sync_failed",
                )
            raise
