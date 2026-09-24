from __future__ import annotations

from pathlib import Path

import pytest


MAINTENANCE_DICTIONARY = Path(__file__).resolve().parents[3] / "ones_mock/ones/查询条件字典.yaml"

requires_maintenance_dictionary = pytest.mark.skipif(
    not MAINTENANCE_DICTIONARY.exists(),
    reason="ones_mock/ones/查询条件字典.yaml 含真实人员与项目，被 .gitignore 排除，只在维护者本机比对",
)

# Field UUIDs mirror the generators' FIELD_SPECS. Options, people, projects,
# statuses and sprints are synthetic. sprint_in must stay after
# all_option_fields because the task-update generator reads field metadata
# comments between those two headings.
SYNTHETIC_ONES_DICTIONARY = """# 查询条件字典：filterGroup 中 UUID -> 中文/显示名
# 数据来源：ONES 团队 MOCK-ONES-TEAM-001，接口拉取日期 2026-08-27。UUID 以接口实时数据为准。
status_in:
  MOCK-STATUS-DONE: 已完成  # 完成
project_in:
  MOCK-PROJECT-A: 合成项目甲
  MOCK-PROJECT-B: 合成项目乙
assign_in:
  MOCK-USER-A: 合成人员甲
  MOCK-USER-B: 合成同名
  MOCK-USER-C: 合成 同名
update_fields_non_option:
  name: 标题
  descriptionText: 描述
  assign: 负责人
  5BiPnrfy: 环境
  F9eyqM3a: 标签
  field040: 解决者
  VRS2LsBn: 所属人
  field008: 关注者
  field011: 所属迭代
  field029: 所属产品
  field030: 所属功能模块
  LMb5XC7P: 解决方案
  DmGDdhkv: Svn版本号
  41TN9bsG: 影响面分析
all_option_fields:
  field041:  # 缺陷类型 type=1
    MOCK-DEFECT-TYPE-FUNCTION: 功能缺陷
  FnkEKd4Y:  # 紧急程度 type=1
    MOCK-URGENCY-HIGH: 紧急
  field038:  # 严重程度 type=1
    MOCK-SEVERITY-BLOCKING: 阻塞
    MOCK-SEVERITY-MINOR: 非阻塞
  4v1yHkX9:  # 发现难易程度 type=1
    MOCK-DIFFICULTY-EASY: 容易
  679m6U93:  # 重现概率 type=1
    MOCK-REPRODUCTION-ALWAYS: 必现
  79WCF8hL:  # 缺陷发现阶段 type=1
    MOCK-STAGE-TEST: 测试阶段
  field031:  # 是否线上缺陷 type=1
    MOCK-ONLINE-NO: 否
  6FimuZwX:  # 是否历史缺陷 type=1
    MOCK-HISTORICAL-NO: 否
  4ipdiS95:  # 影响版本-MES type=16
    MOCK-AFFECTED-V1: V1.0
    MOCK-AFFECTED-V2: V2.0
  MysgAE3y:  # 修复版本-MES type=16
    MOCK-FIXED-V1: V1.1
  LfbLTzsp:  # 验证版本-MES type=16
    MOCK-VERIFIED-V1: V1.2
  PxHXwe6T:  # 缺陷产生原因 type=1
    MOCK-CAUSE-CODE: 编码问题
  field039:  # 处理结果 type=1
    MOCK-RESULT-FIXED: 已修复
  2adoeHHw:  # 多版本重复bug type=1
    MOCK-DUPLICATE-NO: 否
  field012:  # 优先级 type=1
    MOCK-PRIORITY-HIGH: 高
  MOCK-FIELD-UNLISTED:  # 合成未登记字段 type=1
    MOCK-OPTION-UNLISTED: 不应出现
sprint_in:
  MOCK-SPRINT: 合成迭代
"""
