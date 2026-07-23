from __future__ import annotations

from app.bootstrap import build_api_container
from app.shared.config import load_settings
from app.shared.exceptions import NotFound


def main() -> int:
    settings = load_settings()
    container = build_api_container(settings, migrate=True, seed=True)
    service = container.business_application_service
    try:
        container.business_application_repository.get_by_code(
            "default-diagnostic-application"
        )
        print("default-diagnostic-application already exists")
        return 0
    except NotFound:
        pass

    application = service.create(
        actor_id="user_local_admin",
        code="default-diagnostic-application",
        name="默认诊断应用",
        description="未激活的本地控制面草稿，不接管钉钉或Webhook入口。",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    service.save_draft(
        actor_id="user_local_admin",
        code="default-diagnostic-application",
        expected_revision=int(application["revision"]),
        payload={
            "agent_publication_id": "agent_publication_default_v1",
            "workflow_publication_id": "",
            "session_policy": {
                "conversation_mode": "channel",
                "recent_message_limit": 20,
                "retention_days": 30,
                "continuous_conversation_enabled": False,
                "attachments_enabled": False,
            },
            "execution_policy": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "triggers": [],
            "deliveries": [],
            "capabilities": [],
        },
    )
    print("created default-diagnostic-application as an inactive draft")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
