from __future__ import annotations

import unittest

from app.modules.job.domain.job_status import JobStatus
from backend.tests.helpers import container


class RepositoryAndJobTests(unittest.TestCase):
    def test_job_creation_is_idempotent_and_persists_message(self) -> None:
        c = container()
        command = {
            "idempotency_key": "same-key",
            "dingding_conversation_id": "conversation-1",
            "dingding_user_id": "local-user",
            "user_message": "check order",
            "project_code": "default",
            "source": "dingding",
            "correlation_id": "corr-1",
        }

        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        first = c.create_agent_job_service.execute(CreateAgentJobCommand(**command))
        second = c.create_agent_job_service.execute(CreateAgentJobCommand(**command))

        self.assertEqual(first.id, second.id)
        self.assertEqual(1, c.agent_repository.count_rows("agent_job"))
        self.assertEqual(1, c.agent_repository.count_rows("agent_message"))
        self.assertEqual(1, len(c.message_bus.jobs))

    def test_job_claim_and_status_transition(self) -> None:
        c = container()
        from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand

        job = c.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="claim-key",
                dingding_conversation_id="conversation-1",
                dingding_user_id="local-user",
                user_message="check order",
                project_code="default",
            )
        )

        claimed = c.agent_repository.claim_job(job.id, "worker-1")
        duplicate_claim = c.agent_repository.claim_job(job.id, "worker-2")

        self.assertIsNotNone(claimed)
        self.assertIsNone(duplicate_claim)
        c.agent_repository.transition_job(
            job_id=job.id,
            target=JobStatus.SUCCEEDED,
            result="done",
        )
        self.assertEqual(JobStatus.SUCCEEDED, c.agent_repository.get_job(job.id).status)


if __name__ == "__main__":
    unittest.main()
