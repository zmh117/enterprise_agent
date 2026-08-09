from __future__ import annotations

import os

import uvicorn

from services.ones_mcp_server.app import create_app


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.environ.get("ONES_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("ONES_MCP_PORT", "9101")),
        log_level=os.environ.get("ONES_MCP_LOG_LEVEL", "info").lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
