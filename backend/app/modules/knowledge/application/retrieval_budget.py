"""在线知识读取预算；不改变离线索引构建的超时/重试策略。"""

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator, Callable
from datetime import UTC, datetime
import json
import time
from typing import Any
from functools import wraps
from typing import ParamSpec, TypeVar

from app.modules.job.domain.execution_policy import JobExecutionPolicySnapshot
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, strict_object
from app.shared.ones_io_budget import ones_io_budget
from app.shared.io_deadline import IODeadlineExceeded, io_deadline

DEADLINE_HEADER = "X-Knowledge-Deadline-Ms"
MAX_RETRIEVAL_SECONDS = 120
P = ParamSpec("P")
R = TypeVar("R")


@contextmanager
def entry_budget(deadline_ms: int | None = None) -> Iterator[None]:
    seconds: float = MAX_RETRIEVAL_SECONDS
    if deadline_ms is not None:
        if type(deadline_ms) is not int or not 10**12 <= deadline_ms < 10**13:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        seconds = min(seconds, deadline_ms / 1000 - datetime.now(UTC).timestamp())
    try:
        with io_deadline(seconds) as deadline:
            try:
                yield
            except Exception:
                deadline.check()
                raise
    except IODeadlineExceeded:
        raise KnowledgeGovernanceError("knowledge_search_budget_exhausted") from None


def knowledge_entry(function: Callable[P, R]) -> Callable[P, R]:
    """Include first authentication and failure handling, before the Job can be read."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        incoming = kwargs.get("deadline_ms")
        if incoming is not None and type(incoming) is not int:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        with entry_budget(incoming):
            return function(*args, **kwargs)

    return wrapped


def deadline_from_headers(values: list[str]) -> int | None:
    # 仅传递时间上限，不是授权。未提供时仍受本地 120 秒和持久化 Job 预算限制。
    if not values:
        return None
    if (
        len(values) != 1
        or not values[0].isascii()
        or not values[0].isdigit()
        or len(values[0]) != 13
    ):
        raise KnowledgeGovernanceError("knowledge_input_invalid")
    return int(values[0])


_CURRENT: ContextVar["RetrievalBudget | None"] = ContextVar(
    "knowledge_retrieval_budget", default=None
)


class RetrievalBudget:
    def __init__(
        self, job_reader: Callable[[], dict[str, Any]], *, deadline_ms: int | None = None
    ) -> None:
        entered = time.monotonic()
        wall = datetime.now(UTC)
        self._job = job_reader
        with entry_budget(deadline_ms):
            row = self._job()
        try:
            policy = JobExecutionPolicySnapshot.from_dict(
                json.loads(row["execution_policy_json"], object_pairs_hook=strict_object)
            )
            started = datetime.fromisoformat(str(row["locked_at"]))
            if started.tzinfo is None or started > datetime.now(UTC):
                raise ValueError
            remaining = policy.effective.timeout_seconds - (wall - started).total_seconds()
        except (ValueError, TypeError, KeyError):
            raise KnowledgeGovernanceError("knowledge_job_denied") from None
        self.attempt = (row["retry_count"], row["locked_at"], row["execution_policy_json"])
        duration = min(MAX_RETRIEVAL_SECONDS, remaining)
        if deadline_ms is not None:
            if type(deadline_ms) is not int or not 10**12 <= deadline_ms < 10**13:
                raise KnowledgeGovernanceError("knowledge_input_invalid")
            duration = min(duration, deadline_ms / 1000 - wall.timestamp())
        parent = current_budget()
        self._parent = parent
        if parent is not None:
            duration = min(duration, parent.remaining())
        self.deadline = entered + duration
        self.deadline_ms = int((wall.timestamp() + duration) * 1000)
        try:
            with io_deadline(self.remaining()):
                self.check()
        except IODeadlineExceeded:
            raise KnowledgeGovernanceError("knowledge_search_budget_exhausted") from None

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def check(self) -> None:
        if self._parent is not None:
            self._parent.check()
        if self.remaining() <= 0:
            raise KnowledgeGovernanceError("knowledge_search_budget_exhausted")
        row = self._job()
        if (row["retry_count"], row["locked_at"], row["execution_policy_json"]) != self.attempt:
            raise KnowledgeGovernanceError("knowledge_job_denied")

    def headers(self) -> dict[str, str]:
        self.check()
        return {DEADLINE_HEADER: str(self.deadline_ms)}

    @contextmanager
    def activate(self) -> Iterator[None]:
        previous = _CURRENT.set(self)
        try:
            with (
                io_deadline(self.remaining()),
                ones_io_budget(min(MAX_RETRIEVAL_SECONDS, self.remaining())),
            ):
                self.check()
                yield
                self.check()
        except IODeadlineExceeded:
            raise KnowledgeGovernanceError("knowledge_search_budget_exhausted") from None
        finally:
            _CURRENT.reset(previous)


def current_budget() -> RetrievalBudget | None:
    return _CURRENT.get()


def io_timeout(configured: float) -> float:
    budget = current_budget()
    if budget is None:
        return configured
    budget.check()
    return min(configured, budget.remaining())
