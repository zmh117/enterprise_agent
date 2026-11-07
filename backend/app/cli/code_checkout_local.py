"""无数据库、无模型的本地部署检出入口。"""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_client import (
    WorkingCopyClient,
    registry,
    selection,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["browse", "checkout"])
    parser.add_argument("--revision", type=int)
    parser.add_argument("--folder", default="mes")
    parser.add_argument("--select", action="append")
    args = parser.parse_args()
    try:
        entry = registry(Path("/etc/code-svn/checkout.json"))["mes-local"]
        client = WorkingCopyClient(entry, Path("/run/code-svn-auth"))
        result = client.browse(args.revision)
        if args.command == "checkout":
            paths = selection(args.select or [""], result["directories"] + result["files"])
            result = client.checkout(
                root=Path("/var/lib/code-svn/checkout"),
                folder=args.folder,
                job_id=uuid4().hex,
                revision=result["revision"],
                paths=paths,
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error_code": exc.code
                    if isinstance(exc, CodeKnowledgeError)
                    else "code_checkout_failed"
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
