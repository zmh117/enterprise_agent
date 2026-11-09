"""Data contracts for evidence-backed answers, independent of checkout and model identity."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import re
from typing import Any
import unicodedata

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.domain.models import KnowledgeJobAccess


CODE_ANSWER_CONTRACT = "code-answer/v1"
MAX_RESPONSE_BYTES = 512 * 1024


def code_authorization_hash(access: KnowledgeJobAccess) -> str:
    return digest(asdict(access))


def svn_revision(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 9223372036854775807:
        raise CodeKnowledgeError("SVN_REVISION_REQUIRED")
    return value


def code_path(value: Any, *, root: bool = False) -> str:
    if value == "" and root:
        return ""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or "\\" in value
        or any(ord(c) < 32 for c in value)
        or value.startswith(("/", "-"))
        or any(p in {"", ".", ".."} or p.casefold() == ".svn" for p in value.split("/"))
        or ":" in value
    ):
        raise CodeKnowledgeError("CODE_PATH_INVALID")
    return value


def path_in_scope(path: str, scope: list[str]) -> bool:
    return any(prefix == "" or path == prefix or path.startswith(prefix + "/") for prefix in scope)


def normalized_question(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
        raise CodeKnowledgeError("CODE_QUESTION_INVALID")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def bounded_json(value: Any, *, expected: type, limit: int = 64 * 1024) -> Any:
    if not isinstance(value, expected):
        raise CodeKnowledgeError("CODE_PAYLOAD_INVALID")
    try:
        encoded = canonical_json(value)
    except (ValueError, TypeError, RecursionError):
        raise CodeKnowledgeError("CODE_PAYLOAD_INVALID") from None
    if len(encoded.encode()) > limit:
        raise CodeKnowledgeError("CODE_PAYLOAD_TOO_LARGE")
    return value


def utc_time(value: Any) -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, TypeError):
        raise CodeKnowledgeError("CODE_DEADLINE_INVALID") from None


def answer_identity(
    question: str, conditions: dict[str, Any], scope: dict[str, Any]
) -> dict[str, Any]:
    normalized = normalized_question(question)
    bounded_json(conditions, expected=dict)
    bounded_json(scope, expected=dict)
    values = dict(
        question_hash=digest(normalized),
        conditions_hash=digest(conditions),
        visibility_scope_hash=digest(scope),
    )
    return dict(
        question_text=normalized,
        conditions_json=conditions,
        visibility_scope_json=scope,
        identity_hash=digest([CODE_ANSWER_CONTRACT, values]),
        **values,
    )


@dataclass(frozen=True)
class CodeAnalysisContext:
    """Created by authenticated admission; never deserialize this from model parameters."""

    job_id: str
    invocation_id: str
    owner_instance_id: str
    actor_id: str
    knowledge_base_id: str
    config_revision_id: str
    source_id: str
    checkout_id: str
    revision: int
    exact_search_id: str
    question_hash: str
    authorization_hash: str
    deadline_at: str

    def fingerprint(self) -> str:
        return digest(
            {
                **self.__dict__,
                "deadline_at": utc_time(self.deadline_at).isoformat(timespec="microseconds"),
            }
        )
