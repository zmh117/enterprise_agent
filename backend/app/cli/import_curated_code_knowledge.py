"""Import administrator-authored source review without any model/index invocation."""

import argparse
import json
import os
from pathlib import Path

from app.bootstrap import build_api_container
from app.modules.knowledge.domain.code_contracts import MAX_PACKAGE_BYTES, CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_curated_import import CodeCuratedImport
from app.shared.config import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="导入独立源码审校候选；不调用模型、不索引、不启用")
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--original-build-id", required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--review-reference", required=True)
    parser.add_argument("--package", required=True, type=Path)
    args = parser.parse_args()
    runtime = None
    try:
        with args.package.open("rb") as stream:
            raw = stream.read(MAX_PACKAGE_BYTES + 1)
        runtime = build_api_container(load_settings(), seed=False)
        if runtime.knowledge_services is None:
            raise CodeKnowledgeError("code_source_review_import_unavailable")
        result = CodeCuratedImport(
            runtime.database,
            runtime.knowledge_services.sources(),
            Path(os.environ.get("CODE_SOURCE_SNAPSHOT_ROOT", "/var/lib/code-knowledge/sources")),
        ).import_package(
            actor_id=args.actor_id,
            original_build_id=args.original_build_id,
            expected_digest=args.expected_digest,
            review_reference=args.review_reference,
            raw=raw,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except CodeKnowledgeError as exc:
        print(json.dumps({"error_code": exc.code}))
        return 1
    except Exception:
        print(json.dumps({"error_code": "code_source_review_import_unavailable"}))
        return 1
    finally:
        if runtime is not None:
            runtime.database.close()


if __name__ == "__main__":
    raise SystemExit(main())
