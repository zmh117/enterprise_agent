from __future__ import annotations

from dataclasses import dataclass
from typing import Any


FIXTURE_TIME_BASE = "2026-01-15T08:00:00Z"
FIXTURE_NAMESPACE = "agent_test"


@dataclass(frozen=True)
class FixtureTable:
    name: str
    primary_key: str
    columns: tuple[str, ...]
    semantic: str


TABLES: tuple[FixtureTable, ...] = (
    FixtureTable(
        name="production_order",
        primary_key="order_no",
        columns=(
            "order_no",
            "product_code",
            "planned_qty",
            "completed_qty",
            "status",
            "planned_start_at",
            "planned_end_at",
            "actual_start_at",
            "actual_end_at",
            "updated_at",
        ),
        semantic="生产订单：计划、产量、状态和时间边界",
    ),
    FixtureTable(
        name="equipment",
        primary_key="equipment_code",
        columns=(
            "equipment_code",
            "equipment_name",
            "status",
            "last_heartbeat_at",
            "current_order_no",
            "updated_at",
        ),
        semantic="设备：运行状态、心跳和当前订单",
    ),
    FixtureTable(
        name="equipment_alarm",
        primary_key="alarm_id",
        columns=(
            "alarm_id",
            "equipment_code",
            "severity",
            "alarm_code",
            "message",
            "occurred_at",
            "cleared_at",
        ),
        semantic="设备告警：等级、代码、发生和清除时间",
    ),
    FixtureTable(
        name="material_inventory",
        primary_key="inventory_id",
        columns=(
            "inventory_id",
            "material_code",
            "batch_no",
            "onhand_qty",
            "reserved_qty",
            "updated_at",
        ),
        semantic="物料库存：批次、在库、预留和可用量",
    ),
    FixtureTable(
        name="quality_inspection",
        primary_key="inspection_id",
        columns=(
            "inspection_id",
            "order_no",
            "result",
            "defect_code",
            "inspected_at",
        ),
        semantic="质量检验：订单检验结果与缺陷代码",
    ),
    FixtureTable(
        name="production_event",
        primary_key="event_id",
        columns=(
            "event_id",
            "order_no",
            "equipment_code",
            "event_type",
            "event_value",
            "occurred_at",
        ),
        semantic="生产事件：订单、设备、事件类型和值的时间线",
    ),
)


ROWS: dict[str, list[dict[str, Any]]] = {
    "production_order": [
        {
            "order_no": "PO-DONE-001",
            "product_code": "SKU-100",
            "planned_qty": 100,
            "completed_qty": 100,
            "status": "COMPLETED",
            "planned_start_at": "2026-01-15 08:00:00",
            "planned_end_at": "2026-01-15 12:00:00",
            "actual_start_at": "2026-01-15 08:05:00",
            "actual_end_at": "2026-01-15 11:50:00",
            "updated_at": "2026-01-15 11:50:00",
        },
        {
            "order_no": "PO-STUCK-001",
            "product_code": "SKU-200",
            "planned_qty": 120,
            "completed_qty": 36,
            "status": "RUNNING",
            "planned_start_at": "2026-01-15 08:00:00",
            "planned_end_at": "2026-01-15 14:00:00",
            "actual_start_at": "2026-01-15 08:10:00",
            "actual_end_at": None,
            "updated_at": "2026-01-15 09:05:00",
        },
    ],
    "equipment": [
        {
            "equipment_code": "EQ-PACK-01",
            "equipment_name": "包装线 1 号机",
            "status": "RUNNING",
            "last_heartbeat_at": "2026-01-15 11:49:30",
            "current_order_no": "PO-DONE-001",
            "updated_at": "2026-01-15 11:50:00",
        },
        {
            "equipment_code": "EQ-MIX-01",
            "equipment_name": "混合线 1 号机",
            "status": "OFFLINE",
            "last_heartbeat_at": "2026-01-15 09:00:00",
            "current_order_no": "PO-STUCK-001",
            "updated_at": "2026-01-15 09:05:00",
        },
    ],
    "equipment_alarm": [
        {
            "alarm_id": "ALM-INFO-001",
            "equipment_code": "EQ-PACK-01",
            "severity": "INFO",
            "alarm_code": "SHIFT_START",
            "message": "班次开始自检完成",
            "occurred_at": "2026-01-15 08:00:30",
            "cleared_at": "2026-01-15 08:02:00",
        },
        {
            "alarm_id": "ALM-CRIT-001",
            "equipment_code": "EQ-MIX-01",
            "severity": "CRITICAL",
            "alarm_code": "TEMP_HIGH",
            "message": "混合缸温度持续超限",
            "occurred_at": "2026-01-15 09:03:00",
            "cleared_at": None,
        },
    ],
    "material_inventory": [
        {
            "inventory_id": "INV-MAT-001-A",
            "material_code": "MAT-001",
            "batch_no": "BATCH-LOW-001",
            "onhand_qty": 45,
            "reserved_qty": 35,
            "updated_at": "2026-01-15 09:04:00",
        },
        {
            "inventory_id": "INV-MAT-002-A",
            "material_code": "MAT-002",
            "batch_no": "BATCH-OK-001",
            "onhand_qty": 300,
            "reserved_qty": 20,
            "updated_at": "2026-01-15 11:30:00",
        },
    ],
    "quality_inspection": [
        {
            "inspection_id": "QI-DONE-001",
            "order_no": "PO-DONE-001",
            "result": "PASS",
            "defect_code": None,
            "inspected_at": "2026-01-15 11:55:00",
        },
        {
            "inspection_id": "QI-STUCK-001",
            "order_no": "PO-STUCK-001",
            "result": "HOLD",
            "defect_code": "TEMP_DRIFT",
            "inspected_at": "2026-01-15 09:10:00",
        },
    ],
    "production_event": [
        {
            "event_id": "EVT-DONE-START",
            "order_no": "PO-DONE-001",
            "equipment_code": "EQ-PACK-01",
            "event_type": "ORDER_START",
            "event_value": "started",
            "occurred_at": "2026-01-15 08:05:00",
        },
        {
            "event_id": "EVT-STUCK-LAST-PROGRESS",
            "order_no": "PO-STUCK-001",
            "equipment_code": "EQ-MIX-01",
            "event_type": "PROGRESS",
            "event_value": "completed_qty=36",
            "occurred_at": "2026-01-15 09:05:00",
        },
        {
            "event_id": "EVT-STUCK-ALARM",
            "order_no": "PO-STUCK-001",
            "equipment_code": "EQ-MIX-01",
            "event_type": "ALARM",
            "event_value": "TEMP_HIGH",
            "occurred_at": "2026-01-15 09:03:00",
        },
    ],
}


EXPECTED_ROW_COUNTS: dict[str, int] = {table: len(rows) for table, rows in ROWS.items()}

EXPECTED_ANOMALIES: dict[str, Any] = {
    "stuck_order": "PO-STUCK-001",
    "stuck_order_db_completed_qty": 36,
    "stuck_order_redis_completed_qty": 72,
    "offline_equipment": "EQ-MIX-01",
    "equipment_db_status": "OFFLINE",
    "equipment_redis_status": "ONLINE",
    "critical_alarm": "TEMP_HIGH",
    "low_inventory_material": "MAT-001",
    "inventory_db_available_qty": 10,
    "inventory_redis_available_qty": 80,
}


@dataclass(frozen=True)
class RedisFixture:
    key: str
    value: str


def redis_namespace(base: str) -> str:
    return f"{FIXTURE_NAMESPACE}:{base}"


def redis_fixtures(base: str) -> tuple[RedisFixture, ...]:
    ns = redis_namespace(base)
    return (
        RedisFixture(f"{ns}:equipment:EQ-MIX-01:status", "ONLINE"),
        RedisFixture(f"{ns}:equipment:EQ-PACK-01:status", "RUNNING"),
        RedisFixture(f"{ns}:order:PO-STUCK-001:progress", "completed_qty=72;planned_qty=120"),
        RedisFixture(f"{ns}:inventory:MAT-001:available_qty", "80"),
    )


BASE_CODES = ("mysql", "sqlserver")


def assert_manifest_consistent() -> None:
    table_names = {table.name for table in TABLES}
    if table_names != set(ROWS):
        raise ValueError("Fixture table definitions and rows are not aligned")
    for table in TABLES:
        for row in ROWS[table.name]:
            missing = set(table.columns) - set(row)
            extra = set(row) - set(table.columns)
            if missing or extra:
                raise ValueError(
                    f"Fixture row for {table.name} has missing={missing} extra={extra}"
                )
