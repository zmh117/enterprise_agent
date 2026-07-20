from __future__ import annotations

import logging
import uuid

from app.bootstrap import Container, build_worker_container
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.shared.config import Settings, load_settings
from app.shared.logging import configure_logging, with_correlation

logger = logging.getLogger(__name__)


class AgentJobWorker:
    def __init__(self, settings: Settings, container: Container | None = None) -> None:
        self.settings = settings
        self.container = container or build_worker_container(
            settings,
            migrate=settings.app_startup_migrate,
            seed=settings.seed_local_config,
        )
        self.worker_id = f"agent-worker-{uuid.uuid4().hex[:8]}"

    def handle(self, message: AgentJobMessage) -> None:
        def run() -> None:
            current = self.container.agent_repository.get_job(message.job_id)
            if self.container.retry_service.reschedule_if_early(
                current, message.correlation_id
            ):
                return
            try:
                self.container.agent_executor.execute(
                    message.job_id,
                    worker_id=self.worker_id,
                    correlation_id=message.correlation_id,
                    fail_on_error=False,
                )
            except Exception as exc:
                job = self.container.agent_repository.get_job(message.job_id)
                safe_message = getattr(exc, "safe_message", str(exc))
                action = self.container.retry_service.handle_failure(
                    job,
                    exc,
                    message.correlation_id,
                )
                self.container.audit_service.record(
                    f"job.failure.{action}",
                    status="FAILED" if action in {"dead", "timeout"} else "RETRYING",
                    summary=safe_message,
                    job_id=job.id,
                    actor_id=self.worker_id,
                )
                if action in {"dead", "timeout"}:
                    self.container.result_delivery_service.deliver_job_failure(
                        job.id,
                        safe_message,
                        error_code=getattr(exc, "error_code", "") or "agent_runtime_error",
                    )
                logger.warning(
                    "Agent job failed; routed to %s job_id=%s error_type=%s safe_message=%s",
                    action,
                    job.id,
                    exc.__class__.__name__,
                    safe_message,
                )

        with_correlation(message.correlation_id, run)

    def run_once(self) -> None:
        if self.container.consumer is None:
            raise RuntimeError("Worker container does not have a message consumer")
        self.container.consumer.consume_agent_jobs(self.handle)

    def run_forever(self) -> None:
        self.run_once()


def main() -> None:
    configure_logging()
    AgentJobWorker(load_settings()).run_forever()


if __name__ == "__main__":
    main()
