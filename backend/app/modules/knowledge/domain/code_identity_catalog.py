"""Server-owned MES identities, not inferred business rules or source state values."""

from copy import deepcopy
from typing import Any

from app.modules.knowledge.domain.normalization import digest

OBJECTS = {
    "factory.work_order": "工厂工单",
    "factory.formula": "处方",
    "factory.main_formula": "主配方",
    "factory.material": "物料主数据",
    "factory.formula_material": "处方物料明细",
    "factory.runtime_formula_material": "工单运行期处方物料",
    "factory.work_center": "工作中心",
    "factory.organization": "工厂组织单元",
    "factory.production_instruction": "生产指令",
    "factory.production_plan": "生产计划",
    "factory.manufacturing_declaration": "报工记录",
    "factory.material_release": "投料单",
    "group.application": "集团应用",
    "group.business_unit": "集团业务单元",
}
MACHINES = {
    "factory.work_order.configuration": {
        "object_key": "factory.work_order",
        "dimension": "组态工单 XPHARMA_WO_INFO.C_STATUS",
    },
    "factory.work_order.execution": {
        "object_key": "factory.work_order",
        "dimension": "运行期工单 XPHARMA_WO_PRODUCTION.C_STATE",
    },
    "group.application.lifecycle": {
        "object_key": "group.application",
        "dimension": "后端集团应用启停状态",
    },
}
ENTRIES = {
    "factory.work_order.publish": ["request", "execute"],
    "factory.work_order.start": ["request", "execute", "status_changed"],
    "factory.work_order.report": ["prepare", "confirm"],
    "group.application.enable": ["request"],
    "group.application.disable": ["request"],
    "group.application.authorization": ["request"],
}
EVENTS = {
    f"{entry}.{event}": {
        "object_key": entry.rsplit(".", 1)[0],
        "entry_id": entry,
        "name": f"{entry} / {event}",
        "machine_key": (
            "group.application.lifecycle"
            if entry.startswith("group.")
            else "factory.work_order.configuration"
            if entry == "factory.work_order.publish" and event == "request"
            else "factory.work_order.execution"
        ),
    }
    for entry, events in ENTRIES.items()
    for event in events
}
CATALOG = {
    "version": "mes-code-identities/v3",
    "objects": OBJECTS,
    "machines": MACHINES,
    "events": EVENTS,
}
CATALOG_HASH = digest(CATALOG)


def identity_catalog() -> dict[str, Any]:
    return deepcopy(CATALOG)


def object_record(key: str) -> dict[str, Any]:
    """Identity anchor only. It cannot assert source-derived state or behavior."""
    return {
        "business_key": key,
        "object_key": key,
        "identity_state": "confirmed",
        "kind": "object",
        "role": "backend",
        "title": OBJECTS[key],
        "fact_class": "identity",
        "summary": "统一对象身份；业务事实见同快照迁移和规则。",
        "object_version": None,
        "states": [],
        "trigger": None,
        "guard": None,
        "transition": None,
        "check_order": [],
        "effects": [],
        "outcomes": [],
        "success_boundary": {
            "description": "身份目录不声明业务执行结果。",
            "phase": "unknown",
            "evidence_ids": [],
        },
        "configuration": [],
        "evidence_ids": [],
        "required_runtime_facts": [],
        "coverage": "analyzed",
        "unknowns": [],
    }
