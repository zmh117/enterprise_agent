"""Explicit administrator source review; never impersonate a Runtime artifact."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.domain.code_contracts import (
    AUTHORING,
    CONTRACT_VERSION,
    MAX_PACKAGE_BYTES,
    CodeKnowledgeError,
    validate,
)
from app.modules.knowledge.domain.code_identity_catalog import CATALOG_HASH
from app.modules.knowledge.domain.code_package import (
    EvidenceSource,
    parse_json,
    sha256,
    verify_candidate,
)
from app.modules.knowledge.domain.governance import checked_hash, checked_identifier
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_build_controller import review_digest
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory
from app.modules.knowledge.infrastructure.code_source import _read_beneath
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.shared.database import Database


class CodeCuratedImport:
    def __init__(
        self, database: Database, admin: KnowledgeAdministration, source_root: Path
    ) -> None:
        self.db, self.admin = database, admin
        self.repo = CodeRepository(database)
        self.sources = CodeSnapshotDirectory(source_root)

    def import_package(
        self,
        *,
        actor_id: str,
        original_build_id: str,
        expected_digest: str,
        review_reference: str,
        raw: bytes,
    ) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        checked_identifier(original_build_id)
        checked_identifier(review_reference)
        checked_hash(expected_digest)
        if not 1 <= len(raw) <= MAX_PACKAGE_BYTES:
            raise CodeKnowledgeError("code_package_invalid_size_or_text")
        try:
            authoring = parse_json(raw.decode("utf-8"))
        except UnicodeError:
            raise CodeKnowledgeError("code_package_requires_utf8") from None
        validate(authoring, AUTHORING)
        original, units = self._original(original_build_id, expected_digest)
        source = self.db.execute_one(
            f"select * from {table(self.db, 'code_source_snapshot')} where id=?",
            (original["source_snapshot_id"],),
        )
        if not source or source["retired_at"] is not None:
            raise CodeKnowledgeError("code_source_unavailable")
        manifest = self.sources.verify(source["id"], source["manifest_hash"])
        package = deepcopy(authoring["entries"])
        if package["manifest.json"]["source_snapshot_id"] != source["id"] or package[
            "manifest.json"
        ]["source_ref"] != decoded(source["source_ref"]):
            raise CodeKnowledgeError("code_candidate_binding_mismatch")
        entries = {key for u in units for key in decoded(u["scope_json"])["entry_ids"]}
        prefixes = {p for u in units for p in decoded(u["scope_json"])["allowed_prefixes"]}
        scope = {"entry_ids": sorted(entries), "allowed_prefixes": sorted(prefixes)}
        evidence_sources = self._sources(source["id"], manifest, package, prefixes)
        configuration = {
            "contract_version": CONTRACT_VERSION,
            "identity_catalog_hash": CATALOG_HASH,
            "origin_kind": "source_review",
            "original_build_id": original_build_id,
            "original_candidate_digest": expected_digest,
            "reviewer_id": actor_id,
            "review_reference": review_reference,
            "input_digest": sha256(raw),
        }
        # The same source lock serializes dispatch, source configuration changes,
        # retirement and this import. No new QUEUED build is externally visible.
        with source_lock(self.db, original["source_id"]), self.db.unit_of_work():
            self.admin.require_admin(actor_id)
            self._original(original_build_id, expected_digest)
            build = self.repo.new_build(
                original["source_id"],
                source["id"],
                purpose="baseline",
                configuration=configuration,
            )
            unit_id = stable_id("code_review_unit", build["build_id"], digest(scope))
            existing = self.db.execute_one(
                f"select state,result_json from {table(self.db, 'code_unit')} where id=?",
                (unit_id,),
            )
            if existing:
                if existing["state"] != "VALIDATED":
                    raise CodeKnowledgeError("code_review_import_incomplete")
                return {
                    **build,
                    "unit_id": unit_id,
                    "created": False,
                    **decoded(existing["result_json"]),
                }
            expected = {
                "contract_version": CONTRACT_VERSION,
                "build_id": build["build_id"],
                "work_unit_id": unit_id,
                "source_snapshot_id": source["id"],
                "source_ref": decoded(source["source_ref"]),
                "scope_hash": digest(scope),
                "config_hash": original["config_hash"],
            }
            package["manifest.json"] = expected
            result = verify_candidate(
                package,
                expected_manifest=expected,
                sources=evidence_sources,
                expected_entries=entries,
            )
            self.repo.store_candidate(build["snapshot_id"], package)
            insert(
                self.db,
                "code_unit",
                {
                    "id": unit_id,
                    "build_id": build["build_id"],
                    "unit_key": "source_review",
                    "scope_json": scope,
                    "state": "VALIDATED",
                    "result_json": result,
                    "artifact_json": {**configuration, "package_digest": digest(package)},
                    "created_at": now(),
                    "updated_at": now(),
                },
            )
            self.db.execute(
                f"update {table(self.db, 'code_build')} set stage='VALIDATING',updated_at=? where id=?",
                (now(), build["build_id"]),
            )
            self.db.execute(
                f"update {table(self.db, 'code_snapshot')} set validation_json=? where id=?",
                (
                    canonical_json({**result, "unit_count": 1, "origin_kind": "source_review"}),
                    build["snapshot_id"],
                ),
            )
            self.admin.record(
                "code_source_review_imported",
                actor_id=actor_id,
                identifier=build["build_id"],
                revision=0,
            )
            return {**build, "unit_id": unit_id, "created": True, **result}

    def _original(
        self, build_id: str, expected_digest: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        original = self.db.execute_one(
            f"select * from {table(self.db, 'code_build')} where id=?", (build_id,)
        )
        if (
            not original
            or original["stage"] not in {"FAILED", "CANCELLED", "INTERRUPTED"}
            or original["active"]
        ):
            raise CodeKnowledgeError("code_review_original_not_stopped")
        units = self.db.execute(
            f"select * from {table(self.db, 'code_unit')} where build_id=? order by id limit 25",
            (build_id,),
        )
        if not 1 <= len(units) <= 24 or review_digest(units) != expected_digest:
            raise CodeKnowledgeError("code_review_candidate_changed")
        pending = self.db.execute_one(
            f"select u.id from {table(self.db, 'code_unit')} u "
            f"join {table(self.db, 'code_build')} b on b.id=u.build_id "
            "join agent_job j on j.id=u.job_id left join agent_runtime_invocation i on i.job_id=j.id "
            "where b.source_id=? and (j.status not in ('SUCCEEDED','FAILED','TIMEOUT') "
            "or (i.invocation_id is not null and i.execution_quiesced_at is null and i.state<>'PREPARED')) limit 1",
            (original["source_id"],),
        )
        if pending:
            raise CodeKnowledgeError("code_prior_execution_unresolved")
        return original, units

    def _sources(
        self,
        source_id: str,
        manifest: dict[str, Any],
        package: dict[str, Any],
        prefixes: set[str],
    ) -> dict[str, EvidenceSource]:
        files = {row["file_id"]: row for row in manifest["files"]}
        sources: dict[str, EvidenceSource] = {}
        for evidence in package["evidence.jsonl"]:
            row = files.get(evidence["file_id"])
            if not row or not any(
                row["path"] == p or row["path"].startswith(p + "/") for p in prefixes
            ):
                raise CodeKnowledgeError("code_evidence_source_unavailable")
            if row["file_id"] not in sources:
                data = _read_beneath(
                    self.sources.root / source_id, "text/" + row["path"], MAX_PACKAGE_BYTES
                )
                sources[row["file_id"]] = EvidenceSource(
                    row["path"], row["raw_hash"], row["representation_hash"], data.decode("utf-8")
                )
            # The reviewer cannot choose an unverified quote hash. All remaining
            # source identity/line/reference checks are made by verify_candidate.
            text = sources[row["file_id"]].text
            lines = text.splitlines(keepends=True)
            start, end = evidence["start_line"], evidence["end_line"]
            if not 1 <= start <= end <= len(lines):
                raise CodeKnowledgeError("code_evidence_lines_invalid")
            evidence["excerpt_hash"] = sha256("".join(lines[start - 1 : end]).encode())
        return sources
