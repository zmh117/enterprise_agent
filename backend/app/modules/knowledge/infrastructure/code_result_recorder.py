"""Host finalization of private code Q&A; never indexes or runs a model."""

import re
import unicodedata
from typing import Any

from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore
from app.modules.job.domain.agent_job import AgentJob
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_environment import (
    declared_environment,
    require_environment,
)
from app.modules.knowledge.domain.code_user_revision import user_svn_revisions
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.code_qa_store import CodeQaStore
from app.shared.database import Database
from app.shared.secret_redaction import redact_sensitive_text

_CITATION = re.compile(r"code-answer:([A-Za-z0-9_-]{1,200})@([A-Za-z0-9_-]{1,200})")


def business_text(text: str, limit: int) -> str:
    """Bounded private prose only; omit quoted input, source blocks and credentials."""
    lines: list[str] = []
    fence: str | None = None
    for line in unicodedata.normalize("NFC", text).splitlines():
        clean = line.strip()
        if clean.startswith(("```", "~~~")):
            marker = clean[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence or clean.startswith(">") or line.startswith(("    ", "\t")):
            continue
        if clean:
            lines.append(clean)
    result = redact_sensitive_text("\n".join(lines))
    return result[: limit - 12] + "\n[内容已截断]" if len(result) > limit else result


class CodeResultRecorder:
    def __init__(self, database: Database) -> None:
        self.db, self.qa = database, CodeQaStore(database)

    def record(self, job: AgentJob, final_answer: str) -> None:
        """Called inside the standard result transaction, including runtime recovery."""
        invocation = f"{job.id}.attempt-{job.retry_count}"
        pool = RuntimePoolStore(self.db)
        if pool.get(invocation) is None:
            return
        request = pool.request(invocation)
        capability = request["prompt"]["retrieved_context"].get("code_source")
        if (
            not isinstance(capability, dict)
            or capability.get("contract") != "code-source-capability/v2"
        ):
            return
        try:
            environment = declared_environment(self.db, job.input_message or "")
            versions = user_svn_revisions(job.input_message or "")
        except CodeKnowledgeError:
            return  # A request for the missing version is not a versioned business answer.
        question = business_text(job.input_message or "", 2000)
        answer = business_text(final_answer, 64000)
        if not question or not answer:
            return
        # References must occur in final prose AND have been read/saved in this invocation.
        citations = set(_CITATION.findall(answer))
        observed, touched = self._read_references(job.id, invocation, environment["id"])
        analyses = self.db.execute(
            f"SELECT a.knowledge_base_id,a.source_id,a.requested_revision,a.state,"
            "a.saved_revision_id,r.document_id "
            f"FROM {self.qa.t('code_analysis')} a LEFT JOIN {self.qa.t('code_answer_revision')} r "
            "ON r.revision_id=a.saved_revision_id WHERE a.job_id=? AND a.invocation_id=? AND a.environment_id=?",
            (job.id, invocation, environment["id"]),
        )
        for analysis in analyses:
            touched.add(analysis["knowledge_base_id"])
            if analysis["saved_revision_id"]:
                observed.append(
                    dict(
                        knowledge_base_id=analysis["knowledge_base_id"],
                        source_id=analysis["source_id"],
                        document_id=analysis["document_id"],
                        revision_id=analysis["saved_revision_id"],
                        requested_revision=analysis["requested_revision"],
                        matched_revision=analysis["requested_revision"],
                        match_kind="exact",
                    )
                )
        sources = capability.get("sources", [])
        for source in sources:
            base, source_id = source["knowledge_base_id"], source["source_id"]
            try:
                require_environment(self.db, source["config_revision_id"], environment["id"])
            except CodeKnowledgeError:
                continue
            if base not in touched and len(sources) != 1:
                continue
            refs = {}
            for ref in observed:
                key = (ref["document_id"], ref["revision_id"])
                if (
                    key not in citations
                    or ref["knowledge_base_id"] != base
                    or ref["source_id"] != source_id
                    or ref["requested_revision"] not in versions
                ):
                    continue
                refs[key] = dict(
                    document_id=key[0],
                    revision_id=key[1],
                    svn_revision=ref["matched_revision"],
                    version_mode="exact" if ref["match_kind"] == "exact" else "next_higher_hint",
                )
            references = [refs[k] for k in sorted(refs)][:100]
            own = [a for a in analyses if a["knowledge_base_id"] == base]
            exact = {r["svn_revision"] for r in references if r["version_mode"] == "exact"}
            status = (
                "conflicted"
                if any(a["state"] == "conflicted" for a in own)
                else "partial"
                if any(a["state"] == "partial" for a in own)
                else "supported"
                if exact == set(versions)
                else "partial"
                if references
                else "unverified"
            )
            cached = any(
                r["revision_id"] not in {a["saved_revision_id"] for a in own} for r in references
            )
            origin = (
                "mixed"
                if own and cached
                else "code_analysis"
                if own
                else "cache"
                if references
                else "unresolved"
            )
            self.qa.record(
                job_id=job.id,
                result_revision=job.retry_count + 1,
                base_id=base,
                actor_id=job.requester_id,
                source_id=source_id,
                environment_id=environment["id"],
                requested_revisions=list(versions),
                question=question,
                answer=answer,
                support_status=status,
                answer_origin=origin,
                references=references,
            )

    def _read_references(
        self, job: str, invocation: str, environment_id: str
    ) -> tuple[list[dict[str, Any]], set[str]]:
        rows = self.db.execute(
            "SELECT m.business_response_json FROM mcp_operation_audit m "
            "JOIN agent_tool_call t ON t.id=m.agent_tool_call_id "
            "WHERE m.job_id=? AND m.invocation_id=? AND m.server_code='knowledge-mcp' "
            "AND m.tool_identifier IN ('knowledge_search','knowledge_get_code_answer') "
            "AND m.parent_audit_id IS NULL AND m.status='SUCCEEDED' "
            "AND t.status='SUCCEEDED' AND m.response_truncated=0 ORDER BY m.id LIMIT 1000",
            (job, invocation),
        )
        observed: list[dict[str, Any]] = []
        touched: set[str] = set()
        for row in rows:
            response = json_value(row["business_response_json"])
            if not isinstance(response, dict):
                continue
            receipt, read = response.get("code_search"), response.get("code_answer_read")
            if isinstance(receipt, dict) and receipt.get("environment_id") == environment_id:
                touched.add(receipt["knowledge_base_id"])
            if isinstance(read, dict) and read.get("environment_id") == environment_id:
                touched.add(read["knowledge_base_id"])
                observed.append(read)
        return observed, touched
