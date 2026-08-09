from __future__ import annotations

import os

import uvicorn

from services.mcp_common import (
    AuthorizedToolContext,
    JobContext,
    PrincipalContext,
    SubjectSnapshot,
    ToolBindingContext,
)
from services.ones_mcp_server.app import create_app


class ProtocolOnlyPlatformStore:
    """Protocol fixture; production create_app never selects this authorizer."""

    def authorize_request(self, claims):
        return JobContext(
            job_id=claims.job_id,
            app_user_id=claims.sub,
            application_publication_id=claims.application_publication_id,
            status="RUNNING",
            subject=SubjectSnapshot(),
        )

    def authorize_tool(self, *, claims, tool_name, required_scope, correlation_id):
        job = self.authorize_request(claims)
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
            job=job,
            binding=ToolBindingContext(
                binding_id="binding-protocol-test",
                subject_snapshot_id="subject-protocol-test",
                server_code="ones-mcp",
                tool_name=tool_name,
                required_scope=required_scope,
                tool_schema_hash="0" * 64,
            ),
        )


def main() -> None:
    uvicorn.run(
        create_app(platform_store=ProtocolOnlyPlatformStore()),
        host="127.0.0.1",
        port=int(os.environ["ONES_MCP_PORT"]),
        access_log=False,
    )


if __name__ == "__main__":
    main()
