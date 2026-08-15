from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "services.file_service.bootstrap:create_default_app",
        factory=True,
        host="0.0.0.0",
        port=9105,
    )


if __name__ == "__main__":
    main()
