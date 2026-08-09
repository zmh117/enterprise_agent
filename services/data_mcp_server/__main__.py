from __future__ import annotations

import os

import uvicorn

from services.data_mcp_server.app import create_app


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.environ.get("DATA_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("DATA_MCP_PORT", "9102")),
        log_level=os.environ.get("DATA_MCP_LOG_LEVEL", "info").lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
