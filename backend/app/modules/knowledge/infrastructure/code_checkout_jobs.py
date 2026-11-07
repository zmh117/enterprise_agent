"""管理员的持久 SVN 浏览/检出任务，与知识构建状态分离。"""

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_checkout_client import (
    FOLDER,
    registry,
    registered_url,
    selection,
)
from app.modules.knowledge.infrastructure.code_repository import decoded
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.shared.database import Database


class CodeCheckoutJobs:
    def __init__(
        self, db: Database, admin: KnowledgeAdministration, registry_file: Path | None = None
    ):
        self.db, self.admin = db, admin
        self.registry_file = registry_file or Path(
            os.environ.get("CODE_CHECKOUT_REGISTRY_FILE", "/etc/code-svn/checkout.json")
        )
        self.t = table(db, "code_checkout_job")

    def snapshot(self) -> dict[str, Any]:
        enabled = os.environ.get("CODE_CHECKOUT_ENABLED") == "true"
        targets = (
            [entry["public_url"] for entry in registry(self.registry_file).values()]
            if enabled
            else []
        )
        rows = self.db.execute(
            f"select id,kind,state,error_code,created_at,updated_at,result_json from {self.t} order by created_at desc,id desc limit 30"
        )
        for row in rows:
            result = decoded(row.pop("result_json"))
            row["result"] = {
                k: v
                for k, v in result.items()
                if k not in {"directories", "files", "registration_hash"}
            }
        return {"enabled": enabled, "urls": targets, "jobs": rows}

    def get(self, job_id: str) -> dict[str, Any]:
        if not isinstance(job_id, str) or not FOLDER.fullmatch(job_id):
            raise CodeKnowledgeError("code_checkout_not_found")
        row = self.db.execute_one(f"select * from {self.t} where id=?", (job_id,))
        if not row:
            raise CodeKnowledgeError("code_checkout_not_found")
        row["request"] = decoded(row.pop("request_json"))
        row["result"] = decoded(row.pop("result_json"))
        return row

    def submit_browse(
        self, *, actor_id: str, url: str, revision: int | None, request_key: str
    ) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        key, entry = registered_url(self.registry_file, url)
        if revision is not None and (type(revision) is not int or revision < 1):
            raise CodeKnowledgeError("code_svn_revision_invalid")
        return self._submit(
            actor_id,
            request_key,
            "browse",
            {
                "registration": key,
                "registration_hash": digest(entry),
                "url": entry["public_url"],
                "revision": revision,
            },
        )

    def submit_checkout(
        self, *, actor_id: str, browse_job_id: str, paths: list[str], folder: str, request_key: str
    ) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        browse = self.get(browse_job_id)
        if (
            browse["actor_id"] != actor_id
            or browse["kind"] != "browse"
            or browse["state"] != "SUCCEEDED"
        ):
            raise CodeKnowledgeError("code_checkout_browse_required")
        selected = selection(
            paths, browse["result"]["directories"] + browse["result"].get("files", [])
        )
        if not isinstance(folder, str) or not FOLDER.fullmatch(folder):
            raise CodeKnowledgeError("code_checkout_destination_invalid")
        return self._submit(
            actor_id,
            request_key,
            "checkout",
            {
                **browse["request"],
                "revision": browse["result"]["revision"],
                "paths": selected,
                "folder": folder,
                "browse_job_id": browse_job_id,
            },
        )

    def _submit(
        self, actor_id: str, request_key: str, kind: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        if os.environ.get("CODE_CHECKOUT_ENABLED") != "true":
            raise CodeKnowledgeError("code_checkout_disabled")
        if not isinstance(request_key, str) or not FOLDER.fullmatch(request_key):
            raise CodeKnowledgeError("code_checkout_request_invalid")
        with source_lock(self.db, "code-checkout-submit"), self.db.unit_of_work():
            self.admin.require_admin(actor_id)
            old = self.db.execute_one(
                f"select id from {self.t} where request_key=?", (request_key,)
            )
            if old:
                prior = self.get(old["id"])
                if (prior["actor_id"], prior["kind"], prior["request"]) != (
                    actor_id,
                    kind,
                    request,
                ):
                    raise CodeKnowledgeError("code_checkout_idempotency_conflict")
                return {"id": prior["id"], "state": prior["state"]}
            count = self.db.execute_one(
                f"select count(*) as n from {self.t} where state in ('QUEUED','RUNNING')"
            )
            if count and count["n"] >= 20:
                raise CodeKnowledgeError("code_checkout_queue_full")
            identifier = uuid4().hex
            insert(
                self.db,
                "code_checkout_job",
                {
                    "id": identifier,
                    "request_key": request_key,
                    "actor_id": actor_id,
                    "kind": kind,
                    "state": "QUEUED",
                    "request_json": request,
                    "result_json": {},
                    "created_at": now(),
                    "updated_at": now(),
                },
            )
            self.admin.record(
                "code_checkout_queued",
                actor_id=actor_id,
                identifier=identifier,
                revision=request.get("revision") or 0,
            )
        return {"id": identifier, "state": "QUEUED"}

    def update(
        self,
        identifier: str,
        state: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.db.execute(
            f"update {self.t} set state=?,result_json=?,error_code=?,updated_at=? where id=?",
            (state, canonical_json(result or {}), error, now(), identifier),
        )
