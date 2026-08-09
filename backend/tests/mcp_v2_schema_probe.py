from __future__ import annotations

import asyncio
import json

from services.data_mcp_server.app import create_server
from services.mcp_common import McpTokenVerifier


class UnusedDataService:
    def prepare(self, context):
        return context


async def main() -> None:
    server = create_server(
        verifier=McpTokenVerifier(
            b"schema-probe-signing-key-at-least-32-bytes",
            audience="data-mcp",
        ),
        platform_store=object(),
        data_service=UnusedDataService(),
    )
    tools = await server.list_tools()
    print(
        json.dumps(
            {tool.name: tool.input_schema for tool in tools},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
