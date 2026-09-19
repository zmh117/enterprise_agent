"""从受限本地文件加载评测集。"""

import os
import json
import stat
from pathlib import Path
from app.modules.knowledge.domain.evaluation import (
    MAX_DATASET_BYTES,
    EvaluationDataset,
    EvaluationError,
    parse_dataset,
    _unique_object,
)


def load_dataset(path: Path) -> EvaluationDataset:
    """Require an owner-only directory/file; no symlink, device, FIFO or oversized input."""
    try:
        parent = path.parent.stat()
        if not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) & 0o077:
            raise EvaluationError("knowledge_evaluation_input_permissions")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_nlink != 1
            ):
                raise EvaluationError("knowledge_evaluation_input_permissions")
            if info.st_size > MAX_DATASET_BYTES:
                raise EvaluationError("knowledge_evaluation_input_limit")
            data = stream.read(MAX_DATASET_BYTES + 1)
        if len(data) > MAX_DATASET_BYTES:
            raise EvaluationError("knowledge_evaluation_input_limit")
        return parse_dataset(json.loads(data, object_pairs_hook=_unique_object))
    except EvaluationError:
        raise
    except (OSError, ValueError, RecursionError):
        raise EvaluationError() from None
