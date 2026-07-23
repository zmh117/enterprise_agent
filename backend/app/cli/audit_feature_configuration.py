from __future__ import annotations

import json
import os
from collections.abc import Mapping

from app.shared.feature_configuration import (
    FeatureConfigurationError,
    feature_migration_report,
)


def build_report(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    values = environ or os.environ
    return feature_migration_report(values.get("APP_ENV", "local"), values)


def main() -> int:
    try:
        report = build_report()
    except FeatureConfigurationError as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "error": str(exc),
                    "write_performed": False,
                    "publication_performed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {"valid": True, **report},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
