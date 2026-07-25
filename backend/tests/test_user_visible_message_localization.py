import ast
import re
from pathlib import Path

from app.shared.exceptions import NonRetryableExecutionError, NotFound


_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


def test_english_safe_messages_are_not_exposed_to_users() -> None:
    error = NonRetryableExecutionError(
        "Internal diagnostic remains in English",
        safe_message="Request validation failed",
        field_errors=[{"field": "name", "message": "Name is required"}],
    )

    assert str(error) == "Internal diagnostic remains in English"
    assert error.safe_message == "操作失败，请检查输入后重试"
    assert error.field_errors == [{"field": "name", "message": "字段值无效"}]


def test_chinese_user_messages_and_technical_fields_are_preserved() -> None:
    error = NonRetryableExecutionError(
        "Internal model connection failure",
        safe_message="模型连接需要轮换 API Key",
        field_errors=[
            {
                "field": "model_policy.model_connection_revision_id",
                "message": "模型连接需要轮换凭据",
            }
        ],
    )

    assert error.safe_message == "模型连接需要轮换 API Key"
    assert error.field_errors == [
        {
            "field": "model_policy.model_connection_revision_id",
            "message": "模型连接需要轮换凭据",
        }
    ]


def test_missing_resources_receive_a_chinese_fallback() -> None:
    error = NotFound("Agent job not found: job_123")

    assert str(error) == "Agent job not found: job_123"
    assert error.safe_message == "未找到请求的资源"


def test_static_safe_message_literals_include_chinese() -> None:
    app_root = Path(__file__).parents[1] / "app"
    violations: list[str] = []
    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg not in {"safe_message", "default_safe_message"}:
                    continue
                static_text = "".join(
                    child.value
                    for child in ast.walk(keyword.value)
                    if isinstance(child, ast.Constant) and isinstance(child.value, str)
                )
                if static_text and not _CJK_PATTERN.search(static_text):
                    violations.append(
                        f"{path.relative_to(app_root)}:{node.lineno}: {static_text}"
                    )

    assert violations == []
