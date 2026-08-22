"""Compatibility exports for domain-scoped backend test support.

New and actively maintained tests should import from ``backend.tests.support``.
This module remains temporarily stable for existing callers while they migrate.
"""

from backend.tests.support.applications import (
    activate_dingtalk_test_application,
    activate_webhook_test_application,
    ensure_agent_publication_mcp_tools as _ensure_agent_publication_mcp_tools,
)
from backend.tests.support.authorization import (
    grant_test_application_access,
    prepare_debug_application_access,
)
from backend.tests.support.channels import (
    dingtalk_payload,
    dingtalk_sign,
    ensure_active_dingtalk_test_enterprise,
)
from backend.tests.support.delivery import (
    dispatch_pending_deliveries,
    enqueue_job_result_for_delivery,
    persisted_agent_job_message,
    publish_pending_agent_jobs,
)
from backend.tests.support.runtime import (
    DirectJobTestPermissionService,
    container,
    direct_job_permission_service_factory,
    test_settings,
)


__all__ = [
    "DirectJobTestPermissionService",
    "_ensure_agent_publication_mcp_tools",
    "activate_dingtalk_test_application",
    "activate_webhook_test_application",
    "container",
    "dingtalk_payload",
    "dingtalk_sign",
    "direct_job_permission_service_factory",
    "dispatch_pending_deliveries",
    "enqueue_job_result_for_delivery",
    "ensure_active_dingtalk_test_enterprise",
    "grant_test_application_access",
    "persisted_agent_job_message",
    "prepare_debug_application_access",
    "publish_pending_agent_jobs",
    "test_settings",
]
