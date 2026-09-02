from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.modules.external_action.repository import ExternalActionRepository
from app.shared.exceptions import RetryableExecutionError


@dataclass(frozen=True, slots=True)
class ExternalActionExecutionOutcome:
    result: dict[str, Any]
    provider_request_id: str = ""
    card_status_text: str = ""


class ExternalActionExecutionAdapter(Protocol):
    def execute(self, intent: dict[str, Any]) -> ExternalActionExecutionOutcome: ...

    def reconcile_interrupted(
        self,
        intent: dict[str, Any],
    ) -> ExternalActionExecutionOutcome | None: ...


class ProviderNeutralExternalActionWorker:
    """Owns the durable claim/lease/recovery and terminal-state orchestration."""

    def __init__(
        self,
        runtime: Any,
        *,
        worker_id: str,
        repository: ExternalActionRepository,
        card_dispatcher: Callable[[dict[str, Any]], None],
        execution_adapters: dict[str, ExternalActionExecutionAdapter],
    ) -> None:
        if set(execution_adapters) != {"dingtalk", "ones"}:
            raise ValueError("External action Provider adapters are incomplete")
        self.runtime = runtime
        self.worker_id = worker_id[:128]
        self.repository = repository
        self.card_dispatcher = card_dispatcher
        self.execution_adapters = dict(execution_adapters)

    def run_once(self) -> bool:
        card = self.repository.claim_card(worker_id=self.worker_id)
        if card is not None:
            self.card_dispatcher(card)
            return True
        recovered = self.repository.claim_stale_for_reconciliation(worker_id=self.worker_id)
        if recovered is not None:
            provider = str(recovered.get("execution_provider_code") or "dingtalk")
            outcome: ExternalActionExecutionOutcome | None = None
            adapter = self.execution_adapters.get(provider)
            try:
                if adapter is not None:
                    outcome = adapter.reconcile_interrupted(recovered)
            except Exception:
                outcome = None
            if outcome is not None:
                self.repository.complete_execution(
                    str(recovered["id"]),
                    result=outcome.result,
                    provider_request_id=outcome.provider_request_id,
                    card_status_text=outcome.card_status_text,
                )
                status = "SUCCEEDED"
                summary = "Interrupted external action reconciled by read-only verification"
            else:
                self.repository.fail_execution(
                    str(recovered["id"]),
                    error_code="external_action_worker_interrupted",
                    error_summary="执行Worker中断，Provider结果未知，禁止自动重放",
                    uncertain=True,
                    card_status_text="执行结果未知，请人工核对",
                )
                status = "FAILED_UNCERTAIN"
                summary = "Interrupted external action requires manual reconciliation"
            self.runtime.audit_service.record(
                "external_action.interrupted",
                status=status,
                summary=summary,
                job_id=str(recovered["job_id"]),
                actor_id=str(recovered["actor_user_id"]),
                payload={
                    "action_intent_id": str(recovered["id"]),
                    "execution_provider_code": provider,
                },
            )
            return True
        intent = self.repository.claim_approved(worker_id=self.worker_id)
        if intent is not None:
            self.execute_intent(intent)
            return True
        return False

    def execute_intent(self, intent: dict[str, Any]) -> None:
        provider = str(intent.get("execution_provider_code") or "dingtalk")
        try:
            adapter = self.execution_adapters.get(provider)
            if adapter is None:
                raise ValueError("External action execution Provider is not registered")
            outcome = adapter.execute(intent)
            self.repository.complete_execution(
                str(intent["id"]),
                result=outcome.result,
                provider_request_id=outcome.provider_request_id,
                card_status_text=outcome.card_status_text,
            )
            self.runtime.audit_service.record(
                "external_action.executed",
                status="SUCCEEDED",
                summary="Confirmed external action executed",
                job_id=str(intent["job_id"]),
                actor_id=str(intent["actor_user_id"]),
                payload={
                    "action_intent_id": str(intent["id"]),
                    "execution_provider_code": provider,
                    "operation_code": str(intent["operation_code"]),
                },
            )
        except Exception as exc:
            uncertain = isinstance(exc, RetryableExecutionError)
            self.repository.fail_execution(
                str(intent["id"]),
                error_code=str(
                    getattr(exc, "error_code", "") or "external_action_execution_failed"
                ),
                error_summary=str(getattr(exc, "safe_message", "") or "外部操作执行失败"),
                uncertain=uncertain,
                card_status_text=str(
                    getattr(exc, "safe_message", "") or "外部操作执行失败，请联系管理员"
                ),
            )
            self.runtime.audit_service.record(
                "external_action.failed",
                status="FAILED_UNCERTAIN" if uncertain else "FAILED",
                summary="Confirmed external action failed safely",
                job_id=str(intent["job_id"]),
                actor_id=str(intent["actor_user_id"]),
                payload={
                    "action_intent_id": str(intent["id"]),
                    "execution_provider_code": provider,
                    "error_code": str(
                        getattr(exc, "error_code", "") or "external_action_execution_failed"
                    ),
                },
            )
