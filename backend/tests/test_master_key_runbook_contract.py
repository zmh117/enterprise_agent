from __future__ import annotations

from pathlib import Path


def test_emergency_master_key_runbook_is_offline_atomic_and_single_key() -> None:
    path = Path(__file__).resolve().parents[2] / "docs" / "emergency-master-key-reencryption.md"
    text = path.read_text(encoding="utf-8")

    for required in (
        "完整维护窗口",
        "停止 API",
        "一个数据库事务",
        "回滚整个事务",
        "原子 rename",
        "配对恢复单元",
        "不得同时保留两把在线 Key",
        "不提供 Web",
        "不实行 Master Key 有效期、定期轮换、在线多 Key keyring",
    ):
        assert required in text
