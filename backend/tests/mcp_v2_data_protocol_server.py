from __future__ import annotations

import os

import uvicorn

from services.data_mcp_server.app import create_app
from services.mcp_common import (
    AuthorizedToolContext,
    JobContext,
    PrincipalContext,
    SubjectSnapshot,
    ToolBindingContext,
)
from services.mcp_common.tool_catalog import get_catalog_entry


class _HealthQuery:
    def execute_one(self, _sql):
        return {"ready": 1}


class ProtocolOnlyPlatformStore:
    """Wire-protocol fixture; provider access is deliberately unreachable."""

    query = _HealthQuery()

    def authorize_request(self, claims):
        return JobContext(
            job_id=claims.job_id,
            app_user_id=claims.sub,
            application_publication_id=claims.application_publication_id,
            status="RUNNING",
            subject=SubjectSnapshot(),
        )

    def authorize_tool(self, *, claims, tool_name, required_scope, correlation_id):
        catalog = get_catalog_entry(f"data-mcp/{tool_name}")
        return AuthorizedToolContext(
            principal=PrincipalContext(
                app_user_id=claims.sub,
                job_id=claims.job_id,
                application_publication_id=claims.application_publication_id,
                audience=claims.aud,
                scopes=claims.scopes,
                token_id=claims.jti,
                correlation_id=correlation_id,
            ),
            job=self.authorize_request(claims),
            binding=ToolBindingContext(
                binding_id="binding-protocol-test",
                subject_snapshot_id="subject-protocol-test",
                server_code="data-mcp",
                tool_name=tool_name,
                required_scope=required_scope,
                tool_schema_hash=catalog.tool_schema_hash,
                resource_code="protocol-resource",
                resource_deployment_id="deployment-protocol-test",
                resource_revision_id="revision-protocol-test",
            ),
        )


class ProviderMustNotRun:
    def prepare(self, context):
        return context

    def __getattr__(self, name):
        raise AssertionError(f"provider method must not run in protocol test: {name}")


def main() -> None:
    uvicorn.run(
        create_app(
            platform_store=ProtocolOnlyPlatformStore(),
            data_service=ProviderMustNotRun(),
        ),
        host="127.0.0.1",
        port=int(os.environ["DATA_MCP_PORT"]),
        access_log=False,
    )


if __name__ == "__main__":
    main()
