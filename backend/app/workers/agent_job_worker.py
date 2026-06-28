from __future__ import annotations

import logging
import uuid

from app.bootstrap import build_container
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.shared.config import Settings, load_settings
from app.shared.logging import configure_logging, with_correlation

logger = logging.getLogger(__name__)


class AgentJobWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.container = build_container(settings, migrate=True, seed=True)
        self.worker_id = f"agent-worker-{uuid.uuid4().hex[:8]}"

    def handle(self, message: AgentJobMessage) -> None:
        def run() -> None:
            try:
                self.container.agent_executor.execute(
                    message.job_id,
                    worker_id=self.worker_id,
                    fail_on_error=False,
                )
            except Exception as exc:
                job = self.container.agent_repository.get_job(message.job_id)
                action = self.container.retry_service.handle_failure(
                    job,
                    exc,
                    message.correlation_id,
                )
                self.container.audit_service.record(
                    f"job.failure.{action}",
                    status="FAILED" if action == "dead" else "RETRYING",
                    summary=getattr(exc, "safe_message", str(exc)),
                    job_id=job.id,
                    actor_id=self.worker_id,
                )
                if action == "dead":
                    session = self.container.agent_repository.get_session(job.session_id)
                    self.container.dingtalk_message_service.send_final_result(
                        session.dingding_conversation_id,
                        self.container.dingtalk_message_service.safe_failure_notice(
                            getattr(exc, "safe_message", str(exc))
                        ),
                    )
                logger.warning("Agent job failed; routed to %s", action)

        with_correlation(message.correlation_id, run)

    def run_once(self) -> None:
        self.container.message_bus.consume_agent_jobs(self.handle)

    def run_forever(self) -> None:
        # The default container uses an in-memory bus for local/dev tests.
        # Production composition should wire RabbitMQConsumer into this class.
        self.run_once()


def main() -> None:
    configure_logging()
    AgentJobWorker(load_settings()).run_forever()


if __name__ == "__main__":
    main()
