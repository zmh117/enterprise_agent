"""知识四层依赖、稳定索引身份与最小镜像接线；仅使用合成数据。"""

import ast
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.knowledge.domain.vector_points import payload, point_id
from app.modules.knowledge.infrastructure.embedding_profile import profile


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "backend/app/modules/knowledge"


def imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "Knowledge uses explicit layer imports"
            yield node.module or ""


@pytest.mark.parametrize("source", sorted((PACKAGE / "domain").glob("*.py")), ids=lambda p: p.name)
def test_domain_has_no_storage_network_or_outer_layer_dependency(source):
    tree = ast.parse(source.read_text())
    forbidden = ("pathlib", "os", "httpx", "requests", "sqlite3", "psycopg", "fastapi", "socket")
    for name in imports(tree):
        assert not name.startswith(forbidden), (source.name, name)
        if name.startswith("app."):
            assert (
                name.startswith("app.modules.knowledge.domain.") or name == "app.shared.exceptions"
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert not (isinstance(node.func, ast.Name) and node.func.id in {"open", "__import__"})


@pytest.mark.parametrize(
    "source", sorted((PACKAGE / "application").glob("*.py")), ids=lambda p: p.name
)
def test_application_depends_on_ports_not_storage_or_transport(source):
    tree = ast.parse(source.read_text())
    for name in imports(tree):
        assert not name.startswith(("pathlib", "httpx", "sqlite3", "psycopg", "fastapi"))
        assert ".infrastructure" not in name and ".api" not in name
        assert name != "app.shared.database"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {
                "database",
                "execute",
                "execute_one",
                "read_text",
                "read_bytes",
            }
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "EmbeddingClient", "QdrantClient", "Database"}


def test_no_flat_compatibility_modules_or_api_client_construction():
    assert {p.name for p in PACKAGE.glob("*.py")} == {"__init__.py"}
    for source in (PACKAGE / "api").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"database", "execute", "execute_one"}
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {
                    "EmbeddingClient",
                    "QdrantClient",
                    "GovernanceStore",
                    "VectorRepository",
                }


def test_existing_profile_and_stable_storage_identities_are_unchanged():
    # Golden values from the pre-refactor contract, not recalculated expected values.
    assert (
        fingerprint(profile()) == "595254deaeae70c19815d4b42847cc468790a2742bbdf4b5bd6703cfefcf22f3"
    )
    assert stable_id("source", "synthetic-source") == "493c2737-588b-5911-8bd4-069e2a8c04c1"
    index = {
        "id": "00000000-0000-0000-0000-000000000001",
        "knowledge_base_id": "base",
        "profile_hash": "profile",
    }
    row = {
        "id": "chunk",
        "document_id": "document",
        "document_revision_id": "revision",
        "embedding_hash": "embedding",
        "chunk_kind": "problem",
    }
    assert point_id(index, row) == "bf369459-8087-5e79-b351-9206e58f0abc"
    assert payload(index, row) == {
        "index_id": index["id"],
        "knowledge_base_id": "base",
        "document_id": "document",
        "revision_id": "revision",
        "chunk_id": "chunk",
        "profile_hash": "profile",
        "embedding_hash": "embedding",
        "chunk_kind": "problem",
    }


def test_composition_closes_embedding_if_qdrant_creation_fails(monkeypatch):
    from app.modules.knowledge.infrastructure import composition

    closed = []

    class Embedding:
        @property
        def http(self):
            return self

        def close(self):
            closed.append(True)

    def fail():
        raise RuntimeError("synthetic unavailable dependency")

    monkeypatch.setattr(composition, "EmbeddingClient", Embedding)
    monkeypatch.setattr(composition, "QdrantClient", fail)
    services = composition.KnowledgeServices(
        None, None, None, None, instance_code="default", provider_origin=""
    )
    with pytest.raises(RuntimeError, match="synthetic unavailable"):
        services.verify_resource()
    assert closed == [True]


def test_embedding_image_copy_whitelist_imports_without_backend_business_modules(tmp_path):
    for line in (ROOT / "services/knowledge_embedding/Dockerfile").read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        _, *sources, target = shlex.split(line)
        if not target.startswith("/app/"):
            continue
        destination = tmp_path / target.removeprefix("/app/")
        destination.mkdir(parents=True, exist_ok=True)
        for name in sources:
            source = ROOT / name
            if source.is_dir():
                shutil.copytree(
                    source,
                    destination,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
            else:
                shutil.copy2(source, destination / source.name)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import services.knowledge_embedding.api; import services.knowledge_embedding.engine; "
            "import sys; assert not any(n.startswith(('app.shared.database', 'app.modules.identity', "
            "'app.modules.knowledge.application')) for n in sys.modules)",
        ],
        cwd=tmp_path,
        env={"PYTHONPATH": f"{tmp_path / 'backend'}:{tmp_path}"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
