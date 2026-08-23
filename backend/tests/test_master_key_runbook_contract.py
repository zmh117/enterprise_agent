from __future__ import annotations

from pathlib import Path


def test_master_key_runbook_refuses_incomplete_reencryption() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "operations"
        / "platform-master-key.md"
    )
    text = path.read_text(encoding="utf-8")

    for required in (
        "没有覆盖全部密文域的受支持重加密工具",
        "platform_secret_version",
        "external_identity_credential",
        "pending challenge",
        "message_attachment",
        "channel_ingress_event",
        "只能停机、隔离、备份并执行事件响应",
        "不得执行数据库重加密或替换 Key 文件",
        "不提供 Web 管理、多 Key keyring",
    ):
        assert required in text
