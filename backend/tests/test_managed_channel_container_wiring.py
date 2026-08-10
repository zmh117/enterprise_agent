from __future__ import annotations

from app.bootstrap import build_test_container
from app.modules.managed_channel.domain import DingTalkApplicationInput
from backend.tests.helpers import test_settings as build_test_settings


def test_managed_channel_service_is_wired_to_the_application_container() -> None:
    container = build_test_container(build_test_settings(), migrate=True, seed=True)
    try:
        enterprise = container.managed_channel_service.create_dingtalk_enterprise(
            name="Acceptance enterprise",
            actor_id="user_local_admin",
        )
        channel = container.managed_channel_service.create_dingtalk(
            DingTalkApplicationInput(
                name="Acceptance robot",
                client_id="acceptance-client-id",
                client_secret="test-only-managed-channel-secret",
                dingtalk_enterprise_id=enterprise["id"],
            ),
            actor_id="user_local_admin",
            enabled=False,
        )

        assert channel["client_id"] == "acceptance-client-id"
        assert channel["secret_configured"] is True
        assert container.managed_channel_service.get_channel(channel["id"])["id"] == channel["id"]
    finally:
        container.database.close()
