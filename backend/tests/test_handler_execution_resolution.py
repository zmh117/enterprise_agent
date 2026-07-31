from __future__ import annotations

import pytest

from app.modules.internal_tools.application.handler_resolution import (
    HandlerExecutionResolver,
    HandlerResolutionRequest,
)
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.modules.platform_config.infrastructure.repository import (
    json_text,
    new_id,
    now_iso,
)
from app.shared.exceptions import PermissionDenied
from backend.tests.helpers import (
    container,
    prepare_debug_application_access,
)


class PassingMysqlVerifier:
    def verify(
        self,
        *,
        resource: dict[str, object],
        draft: dict[str, object],
    ) -> ResourceVerificationOutcome:
        del resource, draft
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="mysql_v1",
            checks={
                "connection": True,
                "readonly_account": True,
            },
        )


class ToggleRoleAuthorizer:
    def __init__(self) -> None:
        self.allowed = True

    def allows(self, **_kwargs: str) -> bool:
        return self.allowed


def _setup_resolution() -> tuple[
    object,
    HandlerExecutionResolver,
    HandlerResolutionRequest,
    dict[str, str],
]:
    runtime = container()
    selection = prepare_debug_application_access(
        runtime,
        application_code="governed-handler-resolution",
        role_code="governed-handler-resolution-role",
        capabilities=("query_database",),
    )
    handlers = runtime.platform_config_service.handlers
    handlers.reconcile(actor_id="local-user")
    handler_publication = handlers.publish_payload(
        {
            "handler_id": "query_database",
            "handler_version": "1.0.0",
        },
        actor_id="local-user",
    )
    runtime.platform_config_service.create_platform_secret(
        {
            "code": "handler_resolution_mysql_password",
            "value": "handler-resolution-canary-password",
        },
        actor_id="local-user",
    )
    resources = runtime.platform_config_service.governed_resources
    created = resources.create_resource(
        {
            "code": "handler_resolution_mysql",
            "name": "Handler resolution MySQL",
            "resource_kind": "database",
            "scope_type": "base",
            "environment_code": "local",
            "base_code": "debug-base",
            "provider_type": "mysql",
            "config": {
                "host": "mysql.internal",
                "port": 3306,
                "database": "orders",
                "username": "reader",
            },
            "secret_refs": {
                "password_ref": (
                    "secret://platform/"
                    "handler_resolution_mysql_password"
                )
            },
        },
        actor_id="local-user",
    )
    resources.verify_draft(
        "handler_resolution_mysql",
        actor_id="local-user",
        verifier=PassingMysqlVerifier(),
    )
    resource_revision = resources.publish_draft(
        "handler_resolution_mysql",
        actor_id="local-user",
    )
    application_handler_id = new_id("application_handler")
    runtime.database.execute(
        """
        insert into business_application_publication_handler
          (id, application_publication_id, handler_publication_id,
           capability_code, constraints_json, created_at)
        values (?, ?, ?, 'query_database', '{}', ?)
        """,
        (
            application_handler_id,
            selection["publication_id"],
            handler_publication["id"],
            now_iso(),
        ),
    )
    runtime.database.execute(
        """
        insert into business_application_publication_resource
          (id, application_handler_id, resource_slot,
           resource_revision_id, constraints_json, binding_hash,
           created_at)
        values (?, ?, 'database', ?, ?, ?, ?)
        """,
        (
            new_id("application_resource"),
            application_handler_id,
            resource_revision["id"],
            json_text(
                {
                    "environment_code": "local",
                    "base_code": "debug-base",
                    "workshop_code": "",
                }
            ),
            "a" * 64,
            now_iso(),
        ),
    )
    role = ToggleRoleAuthorizer()
    resolver = HandlerExecutionResolver(
        runtime.database,
        handlers.registry,
        role,
    )
    request = HandlerResolutionRequest(
        user_id="user_local_admin",
        application_id=selection["application_id"],
        application_publication_id=selection["publication_id"],
        agent_publication_id="agent_publication_default_v1",
        agent_classification="internal_diagnostic",
        capability_code="query_database",
        handler_id="query_database",
        handler_version="1.0.0",
        environment_code="local",
        base_code="debug-base",
    )
    facts = {
        "handler_publication_id": str(handler_publication["id"]),
        "application_handler_id": application_handler_id,
        "resource_revision_id": str(resource_revision["id"]),
        "resource_id": str(created["resource"]["id"]),
    }
    facts["role"] = role  # type: ignore[assignment]
    return runtime, resolver, request, facts


def test_handler_resolution_requires_full_governance_intersection() -> None:
    runtime, resolver, request, facts = _setup_resolution()
    role = facts["role"]
    try:
        resolved = resolver.resolve(request)
        assert resolved.handler_publication_id == facts[
            "handler_publication_id"
        ]
        assert resolved.application_handler_id == facts[
            "application_handler_id"
        ]
        assert resolved.resources[0].resource_revision_id == facts[
            "resource_revision_id"
        ]

        def denied(match: str = "Handler") -> None:
            with pytest.raises(
                PermissionDenied,
                match=match,
            ):
                resolver.resolve(request)

        runtime.database.execute(
            """
            update handler_installation
               set installation_status = 'DRIFTED'
             where handler_id = 'query_database'
            """
        )
        denied()
        runtime.database.execute(
            """
            update handler_installation
               set installation_status = 'INSTALLED'
             where handler_id = 'query_database'
            """
        )

        runtime.database.execute(
            """
            update handler_publication set status = 'DISABLED'
             where id = ?
            """,
            (facts["handler_publication_id"],),
        )
        denied()
        runtime.database.execute(
            """
            update handler_publication set status = 'PUBLISHED'
             where id = ?
            """,
            (facts["handler_publication_id"],),
        )

        runtime.database.execute(
            """
            update business_application_publication_handler
               set capability_code = 'query_loki'
             where id = ?
            """,
            (facts["application_handler_id"],),
        )
        denied()
        runtime.database.execute(
            """
            update business_application_publication_handler
               set capability_code = 'query_database'
             where id = ?
            """,
            (facts["application_handler_id"],),
        )

        publication_snapshot = runtime.database.execute_one(
            """
            select snapshot_json from business_application_publication
             where id = ?
            """,
            (request.application_publication_id,),
        )
        assert publication_snapshot is not None
        runtime.database.execute(
            """
            update business_application_publication
               set snapshot_json = '{}'
             where id = ?
            """,
            (request.application_publication_id,),
        )
        denied("snapshot digest")
        runtime.database.execute(
            """
            update business_application_publication
               set snapshot_json = ?
             where id = ?
            """,
            (
                publication_snapshot["snapshot_json"],
                request.application_publication_id,
            ),
        )

        agent_binding = runtime.database.execute_one(
            """
            select * from agent_tool_binding
             where publication_id = 'agent_publication_default_v1'
               and tool_name = 'query_database'
            """
        )
        assert agent_binding is not None
        runtime.database.execute(
            "delete from agent_tool_binding where id = ?",
            (agent_binding["id"],),
        )
        denied()
        runtime.database.execute(
            """
            insert into agent_tool_binding
              (id, publication_id, tool_name, created_at)
            values (?, ?, ?, ?)
            """,
            (
                agent_binding["id"],
                agent_binding["publication_id"],
                agent_binding["tool_name"],
                agent_binding["created_at"],
            ),
        )

        role.allowed = False  # type: ignore[union-attr]
        denied()
        role.allowed = True  # type: ignore[union-attr]

        runtime.database.execute(
            """
            update business_application_publication_resource
               set resource_slot = 'other_database'
             where application_handler_id = ?
            """,
            (facts["application_handler_id"],),
        )
        denied()
        runtime.database.execute(
            """
            update business_application_publication_resource
               set resource_slot = 'database'
             where application_handler_id = ?
            """,
            (facts["application_handler_id"],),
        )

        runtime.database.execute(
            """
            update platform_resource_revision set status = 'DISABLED'
             where id = ?
            """,
            (facts["resource_revision_id"],),
        )
        denied()
        runtime.database.execute(
            """
            update platform_resource_revision set status = 'PUBLISHED'
             where id = ?
            """,
            (facts["resource_revision_id"],),
        )

        with pytest.raises(PermissionDenied):
            resolver.resolve(
                HandlerResolutionRequest(
                    **{
                        **request.__dict__,
                        "base_code": "other-base",
                    }
                )
            )
    finally:
        runtime.database.close()


def test_query_database_is_available_to_business_agent_classification() -> None:
    runtime, resolver, request, _facts = _setup_resolution()
    try:
        resolved = resolver.resolve(
            HandlerResolutionRequest(
                **{
                    **request.__dict__,
                    "agent_classification": "business",
                }
            )
        )
        assert resolved.definition.handler_id == "query_database"
        assert "query_database" in {
            definition.handler_id
            for definition in resolver.registry.application_catalog()
        }
    finally:
        runtime.database.close()
