"""First MES work-unit locations. Lexical hints are never treated as business knowledge."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import posixpath
import re
from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError, MAX_PACKAGE_BYTES
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import digest, canonical_json
from app.modules.knowledge.infrastructure.code_repository import decoded
from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory
from app.modules.knowledge.infrastructure.code_source import _read_beneath, component_role
from app.modules.knowledge.infrastructure.storage import insert, table
from app.shared.database import Database

FACTORY = "set_web/EBR/src/"
GROUP = "set_web/JTH/src/"
BACKEND = "set_server/mes_business/"
WORKFLOW = "set_server/mes_core_mod/MDWorkflowRun/src/WorkflowEngine/"
ENTRY_STARTS = {
    "factory.work_order.publish": (
        BACKEND + "MDWOCfg/src/Logic/EBRWoSetOpr.cpp",
        BACKEND + "MDEBRCache/src/CachedWorkOrder.cpp",
        FACTORY + "view/production/workOrderPublish.vue",
    ),
    "factory.work_order.start": (
        BACKEND + "MDWORun/src/Logic/WOKernel.cpp",
        WORKFLOW + "WorkflowEngine.cpp",
        WORKFLOW + "Workflow.cpp",
        BACKEND + "MDEBRCache/src/CachedWorkOrder.cpp",
        FACTORY + "view/execute/WoList.vue",
        FACTORY + "view/execute/Layout.vue",
        FACTORY + "api/api-worun.js",
    ),
    "factory.work_order.report": (
        BACKEND + "MDMat/src/Logic/EBRMatOpr.cpp",
        "set_server/mes_public/DataAcc/src/DataAccAPI/CachedMat.cpp",
        "set_server/pubclass/WMSDataHelper.cpp",
        "set_server/include/SafeDBTransaction.hpp",
        "set_server/include/ErrorDefine.h",
        BACKEND + "MDWOCfg/src/Logic/EBRWoSetOpr.cpp",
        FACTORY + "view/production/workOrderConfirm.vue",
        FACTORY + "api/api-wo.js",
        FACTORY + "api/api-mat.js",
    ),
    "group.application.enable": (
        BACKEND + "MDGrouping/GroupingBasic/Logic/GroupingApplication.cpp",
        BACKEND + "MDComponents/DatabaseComponent/GroupAppAuthorize.cpp",
        GROUP + "view/mgt/app/index.vue",
        GROUP + "api/mgt/api-app.js",
        BACKEND + "MDGrouping/GroupingBasic/Logic/GroupingKernel.cpp",
    ),
    "group.application.disable": (
        BACKEND + "MDGrouping/GroupingBasic/Logic/GroupingApplication.cpp",
        BACKEND + "MDComponents/DatabaseComponent/GroupAppAuthorize.cpp",
        GROUP + "view/mgt/app/index.vue",
        GROUP + "api/mgt/api-app.js",
        BACKEND + "MDGrouping/GroupingBasic/Logic/GroupingKernel.cpp",
    ),
    "group.application.authorization": (
        BACKEND + "MDGrouping/GroupingBasic/Logic/GroupingApplication.cpp",
        BACKEND + "MDComponents/DatabaseComponent/GroupAppAuthorize.cpp",
        BACKEND + "MDComponents/DatabaseComponent/GroupBuRelation.cpp",
        BACKEND + "MDComponents/DatabaseComponent/GroupSyncInfo.cpp",
        "set_server/include/SafeDBTransaction.hpp",
        GROUP + "view/mgt/app/index.vue",
        GROUP + "view/mgt/service/app.vue",
        GROUP + "view/mgt/service/auth.vue",
        GROUP + "api/mgt/api-app.js",
        BACKEND + "MDGrouping/GroupingBasic/Logic/GroupingKernel.cpp",
    ),
}
FOCUS_SYMBOLS = {
    "factory.work_order.publish": [
        "SaveAndPublishWo",
        "_PublishWo",
        "_CheckRelatedStatus",
        "CheckPIRelevance",
        "CheckValidity",
        "_UpdateWoPublish",
        "_transToWoRun",
        "_AddWoByType",
        "_AddWo",
        "_UpdateWo",
        "CachedWorkOrder::Publish",
        "CachedWorkOrder::ClearPublishInfo",
    ],
    "factory.work_order.start": [
        "wo_execute",
        "WoRun",
        "CheckWOHandleRun",
        "WfRun",
        "AddWorkflowInsRun",
        "CreateWorkflowIns",
        "SetStatus",
        "onWOStatusChanged",
        "UpdateStatusByWO",
    ],
    "factory.work_order.report": [
        "DeclAck",
        "_UpdateWoStatusToDecl",
        "AddManuDecl",
        "_CheckBatch",
        "APIWOReporting",
        "_calcDeviation",
        "SafeDBTransaction",
        "WMSDataHelper::CheckPoses",
        "WMSDataHelper::_CheckPoses",
        "WMSDataHelper::CheckMatStorage",
    ],
    "group.application.enable": [
        "ChangeApplicationStatus",
        "GroupGroupAppAuthorize::Update",
        "AddSyncInfo",
    ],
    "group.application.disable": [
        "ChangeApplicationStatus",
        "GroupGroupAppAuthorize::Update",
        "AddSyncInfo",
    ],
    "group.application.authorization": [
        "ChangeApplicationScope",
        "GroupGroupAppAuthorize::Update",
        "AddSyncInfo",
    ],
}
COMMON_PREFIXES = (
    "set_server/include",
    "set_server/mes_public/DataAcc/src/DataAccAPI/CachedMat.cpp",
    "set_server/mes_public/DataAcc/src/DataAccAPI/CachedMat.h",
    "set_server/pubclass/WMSDataHelper.cpp",
    "set_server/pubclass/WMSDataHelper.h",
    BACKEND + "MDComponents",
    BACKEND + "MDFormula",
    BACKEND + "MDMat",
    BACKEND + "MDEBRCache",
)
SYMBOL = re.compile(
    r"(?:\b([A-Za-z_]\w*::[A-Za-z_]\w*)\s*\(|^\s*(?:export\s+)?(?:async\s+)?(?:function\s+)?([A-Za-z_]\w*)\s*\([^;]*\)\s*\{)"
)
REFERENCE = re.compile(r"""^\s*#\s*include\s*[<"]([^>"]+)[>"]|\bfrom\s+["']([^"']+)["']""")
CONDITIONAL = re.compile(r"^\s*#\s*(?:if|ifdef|ifndef|elif)\b")
HINT = re.compile(r"status|state|config|permission|msgid|msg_id|protocol", re.I)


class CodeScopePlanner:
    def __init__(self, source_root: Path) -> None:
        self.directory = CodeSnapshotDirectory(source_root)

    def plan(self, snapshot_id: str, manifest_hash: str) -> list[dict[str, Any]]:
        manifest = self.directory.verify(snapshot_id, manifest_hash)
        files = {row["path"]: row for row in manifest["files"]}
        result = []
        for key, starts in ENTRY_STARTS.items():
            prefixes = list(COMMON_PREFIXES)
            prefixes.extend(
                (
                    FACTORY + "view/production",
                    FACTORY + "view/execute",
                    FACTORY + "components/execute",
                    FACTORY + "api",
                    FACTORY + "libs/enum.js",
                    FACTORY + "libs/status.js",
                    FACTORY + "libs/mixin-confirm-event.js",
                    BACKEND + "MDWORun",
                    BACKEND + "MDWOCfg",
                    WORKFLOW.rstrip("/"),
                )
                if key.startswith("factory.")
                else (
                    GROUP + "view/mgt/app",
                    GROUP + "view/mgt/service",
                    GROUP + "api/mgt",
                    GROUP + "enums",
                    GROUP + "libs/enum.js",
                    GROUP + "mixins/page.js",
                    BACKEND + "MDGrouping",
                )
            )
            hints, references, unknowns = [], [], []
            scan_paths = sorted(
                path
                for path in files
                if any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)
            )
            for path in [*starts, *(path for path in scan_paths if path not in starts)]:
                if path not in files:
                    unknowns.append({"code": "entry_source_unavailable", "path": path})
                    continue
                content = _read_beneath(
                    self.directory.root / snapshot_id, "text/" + path, MAX_PACKAGE_BYTES
                ).decode("utf-8")
                scan = locate(path, content, set(files))
                hints.extend(scan["locations"])
                references.extend(scan["references"])
                unknowns.extend(scan["unknowns"])
            result.append(
                {
                    "unit_key": key,
                    "scope": {
                        "entry_ids": [key],
                        "allowed_prefixes": sorted(set(prefixes)),
                        "start_files": list(starts),
                        "focus_symbols": FOCUS_SYMBOLS[key],
                        "entry_scan": {
                            "strategy": "full_first_scope_rebuild",
                            "files_scanned": len(set(starts) & files.keys())
                            + len(set(scan_paths) - set(starts)),
                        },
                        # Definitions in the entry files must not be displaced by
                        # hundreds of status/config occurrences before a callee.
                        "locations": sorted(
                            hints,
                            key=lambda item: (
                                item.get("symbol", "").rsplit("::", 1)[-1]
                                not in {s.rsplit("::", 1)[-1] for s in FOCUS_SYMBOLS[key]},
                                item["kind"] != "symbol_candidate",
                            ),
                        )[:200],
                        "references": references[:100],
                        "locations_truncated": len(hints) > 200,
                        "references_truncated": len(references) > 100,
                        "locator_unknowns": unknowns[:100],
                        "locator_unknowns_truncated": len(unknowns) > 100,
                        "interpretation": "Locations are lexical navigation hints only. Read and trace actual code; no business rule has been extracted or verified.",
                    },
                }
            )
        return result

    def persist(self, database: Database, build_id: str) -> int:
        build = database.execute_one(
            f"select * from {table(database, 'code_build')} where id=?", (build_id,)
        )
        if not build or build["stage"] not in {"QUEUED", "SOURCE_READY"}:
            raise CodeKnowledgeError("code_scope_build_invalid")
        source = database.execute_one(
            f"select manifest_hash from {table(database, 'code_source_snapshot')} where id=?",
            (build["source_snapshot_id"],),
        )
        if not source:
            raise CodeKnowledgeError("code_source_unavailable")
        units = self.plan(build["source_snapshot_id"], source["manifest_hash"])
        self._parent_context(database, build, units)
        with database.unit_of_work():
            locking = " for update of b,c" if database.engine == "postgres" else ""
            current = database.execute_one(
                f"select b.stage,b.config_hash,c.config_hash as current_config_hash from {table(database, 'code_build')} b "
                f"join {table(database, 'code_binding')} c on c.source_id=b.source_id where b.id=?"
                + locking,
                (build_id,),
            )
            if (
                not current
                or current["stage"] not in {"QUEUED", "SOURCE_READY"}
                or current["config_hash"] != current["current_config_hash"]
            ):
                raise CodeKnowledgeError("code_scope_build_changed")
            for unit in units:
                existing = database.execute_one(
                    f"select scope_json from {table(database, 'code_unit')} where build_id=? and unit_key=?",
                    (build_id, unit["unit_key"]),
                )
                if existing and digest(decoded(existing["scope_json"])) != digest(unit["scope"]):
                    raise CodeKnowledgeError("code_scope_changed")
                insert(
                    database,
                    "code_unit",
                    dict(
                        id=stable_id("code_unit", build_id, unit["unit_key"]),
                        build_id=build_id,
                        unit_key=unit["unit_key"],
                        scope_json=unit["scope"],
                        state="QUEUED",
                        created_at=now(),
                        updated_at=now(),
                    ),
                    conflict="on conflict(build_id,unit_key) do nothing",
                )
        return len(units)

    @staticmethod
    def _parent_context(
        database: Database, build: dict[str, Any], units: list[dict[str, Any]]
    ) -> None:
        if build["parent_snapshot_id"]:
            rows = database.execute(
                f"select d.external_id,p.relative_path from {table(database, 'code_member')} m "
                f"join {table(database, 'document')} d on d.id=m.document_id "
                f"left join {table(database, 'code_dependency')} p on p.revision_id=m.revision_id "
                "where m.snapshot_id=? order by d.external_id,p.relative_path limit 2001",
                (build["parent_snapshot_id"],),
            )
            if len(rows) > 2000:
                raise CodeKnowledgeError("code_dependency_scope_limit")
            for unit in units:
                scope = unit["scope"]
                related = [
                    row
                    for row in rows
                    if row["external_id"].startswith(unit["unit_key"])
                    or (
                        row["relative_path"]
                        and any(
                            (
                                row["relative_path"] == prefix
                                or row["relative_path"].startswith(prefix + "/")
                            )
                            for prefix in scope["allowed_prefixes"]
                        )
                    )
                ]
                scope["prior_business_keys"] = sorted({row["external_id"] for row in related})
                scope["prior_dependency_paths"] = sorted(
                    {row["relative_path"] for row in related if row["relative_path"]}
                )
                # Old references supplement the complete new scope scan; uncertain impact rebuilds all six entries.
                scope["parent_snapshot_id"] = build["parent_snapshot_id"]
        for unit in units:
            if len(canonical_json(unit["scope"]).encode()) > 96 * 1024:
                raise CodeKnowledgeError("code_scope_context_limit")


def locate(path: str, content: str, available: set[str]) -> dict[str, Any]:
    locations, references, unknowns = [], [], []
    for number, line in enumerate(content.splitlines(), 1):
        if len(line) > 8192:
            unknowns.append({"code": "long_line_not_located", "path": path, "line": number})
            continue
        if match := SYMBOL.search(line):
            symbol = match.group(1) or match.group(2)
            if symbol not in {"if", "for", "while", "switch", "catch"}:
                locations.append(
                    {"kind": "symbol_candidate", "path": path, "line": number, "symbol": symbol}
                )
        if HINT.search(line):
            locations.append(
                {"kind": "protocol_state_or_policy_candidate", "path": path, "line": number}
            )
        if CONDITIONAL.search(line):
            unknowns.append(
                {"code": "conditional_compilation_requires_analysis", "path": path, "line": number}
            )
        if match := REFERENCE.search(line):
            target = match.group(1) or match.group(2)
            candidates = _reference_candidates(path, target, available)
            references.append(
                {
                    "path": path,
                    "line": number,
                    "target": target,
                    "candidate_paths": candidates[:20],
                    "resolution": "candidate" if len(candidates) == 1 else "unresolved",
                }
            )
            if len(candidates) != 1:
                unknowns.append(
                    {"code": "reference_requires_analysis", "path": path, "line": number}
                )
    return {"locations": locations, "references": references, "unknowns": unknowns}


def _reference_candidates(path: str, target: str, available: set[str]) -> list[str]:
    # Resolution only chooses known admitted paths. It does not read an arbitrary include path.
    relative = posixpath.normpath(str(PurePosixPath(path).parent / target))
    if target.startswith("@/") and path.startswith("set_web/"):
        relative = "/".join(path.split("/")[:2]) + "/src/" + target[2:]
    direct = {
        relative,
        relative + ".js",
        relative + ".ts",
        relative + ".vue",
        relative + "/index.js",
    } & available
    candidates = direct or {item for item in available if item.endswith("/" + target)}
    return sorted(item for item in candidates if component_role(item) == component_role(path))
