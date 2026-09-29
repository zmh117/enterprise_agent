"""固定公开模型的文件准备；无数据库、平台 Secret 或业务输入。"""

import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
import urllib.request
from typing import Any

from app.modules.knowledge.infrastructure.embedding_profile import MODEL
from app.modules.knowledge.domain.vector_contract import VectorError

MODEL_DIR = Path("/models") / MODEL["revision"]
DEFAULT_HF_ENDPOINT = "https://huggingface.co"


def model_endpoint() -> str:
    endpoint = (os.getenv("HF_ENDPOINT") or DEFAULT_HF_ENDPOINT).strip().rstrip("/")
    try:
        parsed = urlsplit(endpoint)
        valid_port = parsed.port is None or parsed.port > 0
        valid_host = bool(parsed.hostname)
    except ValueError:
        raise VectorError("knowledge_model_endpoint_invalid") from None
    if (
        parsed.scheme != "https"
        or not valid_host
        or not valid_port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in endpoint)
    ):
        raise VectorError("knowledge_model_endpoint_invalid")
    return endpoint


def verify_file(path: Path, expected: dict[str, Any]) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != expected["size"]:
        raise VectorError("knowledge_model_file_invalid")
    sha = hashlib.sha256() if "sha256" in expected else hashlib.sha1()
    if "git_blob" in expected:
        sha.update(f"blob {expected['size']}\0".encode())
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            sha.update(chunk)
    if sha.hexdigest() != expected.get("sha256", expected.get("git_blob")):
        raise VectorError("knowledge_model_file_invalid")


def verify_model(root: Path = MODEL_DIR) -> None:
    if root.is_symlink() or not root.is_dir():
        raise VectorError("knowledge_model_missing")
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    if actual != set(MODEL["files"]) or any(p.is_symlink() for p in root.rglob("*")):
        raise VectorError("knowledge_model_file_invalid")
    for name, expected in MODEL["files"].items():
        verify_file(root / name, expected)


def prepare_model(root: Path = MODEL_DIR) -> None:
    endpoint = model_endpoint()
    if root.is_symlink():
        raise VectorError("knowledge_model_file_invalid")
    root.mkdir(parents=True, exist_ok=True)
    for name, expected in MODEL["files"].items():
        target = root / name
        if target.parent.is_symlink() or target.is_symlink():
            raise VectorError("knowledge_model_file_invalid")
        if target.exists():
            verify_file(target, expected)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        if partial.is_symlink():
            raise VectorError("knowledge_model_file_invalid")
        for attempt in range(3):
            try:
                url = f"{endpoint}/{MODEL['model_id']}/resolve/{MODEL['revision']}/{name}"
                with (
                    urllib.request.urlopen(url, timeout=60) as response,
                    partial.open("wb") as output,
                ):
                    total, reported = 0, 0
                    while chunk := response.read(8 * 1024 * 1024):
                        total += len(chunk)
                        if total > expected["size"]:
                            raise VectorError("knowledge_model_file_invalid")
                        output.write(chunk)
                        if total - reported >= 128 * 1024 * 1024:
                            print(
                                json.dumps(
                                    {
                                        "event": "model_download_progress",
                                        "bytes": total,
                                        "total_bytes": expected["size"],
                                    }
                                ),
                                flush=True,
                            )
                            reported = total
                verify_file(partial, expected)
                partial.replace(target)
                print(json.dumps({"event": "model_file_verified", "file": name}), flush=True)
                break
            except Exception:
                if attempt == 2:
                    raise VectorError("knowledge_model_download_failed") from None
                time.sleep(2**attempt)
    verify_model(root)


if __name__ == "__main__":
    try:
        prepare_model()
        print('{"event":"model_prepared"}', flush=True)
    except Exception:
        print(
            '{"event":"model_prepare_failed","error_code":"knowledge_model_prepare_failed"}',
            flush=True,
        )
        raise SystemExit(1) from None
