from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = ROOT / "backend/app/python_runtime"
RUNTIME_PACKAGE = "app.python_runtime"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _runtime_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if node.level:
            imports.add(node.module.split(".", 1)[0])
            continue
        if node.module.startswith(f"{RUNTIME_PACKAGE}."):
            imports.add(node.module.removeprefix(f"{RUNTIME_PACKAGE}." ).split(".", 1)[0])
    return imports


def test_application_owns_the_single_runtime_client_port() -> None:
    executor = ROOT / "backend/app/modules/agent/application/agent_executor.py"
    port = ROOT / "backend/app/modules/agent/application/runtime_client.py"
    bootstrap = (ROOT / "backend/app/bootstrap.py").read_text(encoding="utf-8")

    executor_imports = {
        node.module for node in ast.walk(_tree(executor)) if isinstance(node, ast.ImportFrom)
    }
    port_imports = {
        node.module for node in ast.walk(_tree(port)) if isinstance(node, ast.ImportFrom)
    }

    assert "app.modules.agent.application.runtime_client" in executor_imports
    assert not any(
        module and module.startswith("app.modules.agent.infrastructure")
        for module in port_imports
    )
    assert "RuntimeClientRegistry" not in bootstrap
    assert "runtime_clients" not in bootstrap
    assert "RoutedAgentRuntimeClient" not in bootstrap
    assert not (ROOT / "backend/app/modules/agent/infrastructure/routed_runtime_client.py").exists()


def test_python_runtime_modules_are_acyclic_and_do_not_import_private_symbols() -> None:
    modules = {path.stem: path for path in RUNTIME_ROOT.glob("*.py") if path.stem != "__init__"}
    graph = {
        name: {dependency for dependency in _runtime_imports(path) if dependency in modules}
        for name, path in modules.items()
    }

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        assert name not in visiting, f"Python Runtime import cycle detected at {name}"
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for module_name in graph:
        visit(module_name)

    for path in modules.values():
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_module = node.module or ""
            is_runtime_import = node.level > 0 or imported_module.startswith(RUNTIME_PACKAGE)
            if not is_runtime_import:
                continue
            assert not [name.name for name in node.names if name.name.startswith("_")], path

    assert not graph["claude_client"].intersection({"executor", "service", "invocations"})
    assert not graph["mcp_config"].intersection({"executor", "service", "invocations"})
    assert not graph["tool_policy"].intersection({"executor", "service", "invocations"})
    assert "executor" in graph["service"]


def test_python_runtime_has_no_dynamic_plugin_or_runtime_registry() -> None:
    governed_modules = (
        "claude_client.py",
        "mcp_config.py",
        "tool_policy.py",
        "executor.py",
    )
    combined = "\n".join(
        (RUNTIME_ROOT / name).read_text(encoding="utf-8") for name in governed_modules
    )
    forbidden_markers = (
        "pkgutil.iter_modules",
        "importlib.metadata.entry_points",
        "RuntimeClientRegistry",
        "RoutedAgentRuntimeClient",
        "client_registry",
        "server_registry",
        "plugin_registry",
    )
    assert not [marker for marker in forbidden_markers if marker in combined]

    dynamic_imports: list[str] = []
    for name in governed_modules:
        for node in ast.walk(_tree(RUNTIME_ROOT / name)):
            if not isinstance(node, ast.Call):
                continue
            if not (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
            ):
                continue
            assert len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
            dynamic_imports.append(str(node.args[0].value))
    assert dynamic_imports == ["claude_agent_sdk", "claude_code_sdk"]


def test_sdk_client_has_no_business_state_dependencies() -> None:
    source = (RUNTIME_ROOT / "claude_client.py").read_text(encoding="utf-8")
    forbidden = (
        "AgentRepository",
        "JobRepository",
        "RabbitMQ",
        "delivery_outbox",
        "retry_service",
        "RuntimeClientRegistry",
    )
    assert not [name for name in forbidden if name in source]
