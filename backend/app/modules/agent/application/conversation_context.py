from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.job.domain.agent_job import AgentJob
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.config import ConversationSettings
from app.shared.exceptions import PermissionDenied


class ConversationSummarizer(Protocol):
    def summarize(self, previous: str, messages: list[dict[str, object]], max_chars: int) -> str: ...


class BoundedConversationSummarizer:
    """MVP deterministic summarizer; preserves attribution without a second model call."""

    def summarize(self, previous: str, messages: list[dict[str, object]], max_chars: int) -> str:
        lines = [previous] if previous else []
        for message in messages:
            sender = str(message.get("sender_display_name") or message.get("sender_id") or "")
            role = str(message.get("role") or "message")
            prefix = f"{role}({sender})" if sender else role
            lines.append(f"{prefix}: {message.get('content') or ''}")
        return "\n".join(lines)[-max_chars:]


@dataclass(frozen=True)
class ConversationContext:
    summary: str
    recent_messages: list[dict[str, object]]
    attachments: list[dict[str, object]]
    truncated: bool

    def prompt_text(self) -> str:
        parts = [self.summary] if self.summary else []
        for message in self.recent_messages:
            sender = str(message.get("sender_display_name") or message.get("sender_id") or "")
            role = str(message.get("role") or "message")
            parts.append(f"{role}{f'({sender})' if sender else ''}: {message.get('content') or ''}")
        return "\n".join(parts)


class ConversationContextService:
    def __init__(
        self,
        repository: AgentRepository,
        settings: ConversationSettings,
        summarizer: ConversationSummarizer | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.summarizer = summarizer or BoundedConversationSummarizer()

    def build(self, job: AgentJob) -> ConversationContext:
        session = self.repository.get_session(job.session_id)
        if session.project_code != job.project_code:
            raise PermissionDenied("Conversation project scope mismatch")
        if session.conversation_type == "direct" and session.requester_id != job.requester_id:
            raise PermissionDenied("Conversation requester scope mismatch")
        messages = self.repository.list_messages(
            job.session_id,
            limit=self.settings.recent_message_limit + self.settings.summary_trigger_messages,
        )
        summary = session.summary_text
        if len(messages) > self.settings.summary_trigger_messages:
            cutoff = len(messages) - self.settings.recent_message_limit
            older = messages[:cutoff]
            try:
                candidate = self.summarizer.summarize(
                    summary,
                    older,
                    self.settings.max_summary_chars,
                )
                through = int(older[-1]["sequence_no"]) if older else session.summary_through_sequence
                if self.repository.update_session_summary(
                    session.id,
                    expected_version=session.summary_version,
                    summary_text=candidate,
                    through_sequence=through,
                ):
                    summary = candidate
                messages = messages[cutoff:]
            except Exception:
                messages = messages[-self.settings.recent_message_limit :]
        else:
            messages = messages[-self.settings.recent_message_limit :]
        attachments = self.repository.list_attachment_context(
            job.id,
            max_chars=self.settings.max_attachment_context_chars,
        )
        summary, messages, truncated = _fit_budget(
            summary,
            messages,
            self.settings.max_context_chars,
        )
        return ConversationContext(
            summary=summary,
            recent_messages=messages,
            attachments=attachments,
            truncated=truncated or any(bool(item.get("truncated")) for item in attachments),
        )


def _fit_budget(
    summary: str,
    messages: list[dict[str, object]],
    max_chars: int,
) -> tuple[str, list[dict[str, object]], bool]:
    summary = summary[-min(len(summary), max_chars // 2) :]
    selected: list[dict[str, object]] = []
    used = len(summary)
    for message in reversed(messages):
        content = str(message.get("content") or "")
        if used + len(content) > max_chars:
            break
        selected.append(message)
        used += len(content)
    selected.reverse()
    return summary, selected, len(selected) < len(messages)
