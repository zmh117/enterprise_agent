from __future__ import annotations

from typing import Final


NOTABLE_REFERENCE_SOURCE_VERSION: Final = "dingtalk-mcp@1.1.21"

NOTABLE_SUPPORTED_SEARCH_FILTERS: Final = """AI 表格条件查询格式（固定官方参考）：
- 文本：equal、notEqual、contain、notContain、empty、notEmpty；值示例 ["abc"]。
- 数字：equal、notEqual、greater、greaterEqual、less、lessEqual、empty、notEmpty；值示例 ["123"]。
- 单选/多选：equal、notEqual、contain、notContain、empty、notEmpty；值为选项名或选项 ID 数组。
- 日期：equal、greater、less、empty、notEmpty；值为日期字符串或时间戳数组。
- 人员：equal、notEqual、contain、notContain、empty、notEmpty；值示例 [{"unionId":"xxx"}]。
- 部门：equal、notEqual、contain、notContain、empty、notEmpty；值示例 [{"deptId":"xxx"}]。
empty/notEmpty 条件不需要值。"""

NOTABLE_SUPPORTED_FIELD_INFO: Final = """AI 表格字段类型与 property（固定官方参考）：
- text：无 property。
- number：formatter 可为 INT、FLOAT_1..4、THOUSAND、THOUSAND_FLOAT、PRESENT、PRESENT_FLOAT、CNY/CNY_FLOAT、HKD/HKD_FLOAT、USD/USD_FLOAT、EUR/EUR_FLOAT、JPY/JPY_FLOAT。
- singleSelect / multipleSelect：property.choices 为 [{"name":"选项名"}]。
- date：property.formatter 可为 YYYY-MM-DD、YYYY-MM-DD HH:mm、YYYY-MM-DD HH:mm:ss、YYYY/MM/DD、YYYY/MM/DD HH:mm。
- user / department：property.multiple 为 boolean，默认 true。
- attachment：无 property。
- unidirectionalLink：property 包含 multiple 与 linkedSheetId。
- bidirectionalLink：property 包含 multiple、linkedSheetId，可包含 linkedFieldId。
- url：无 property。"""

NOTABLE_RECORD_VALUES_FORMAT: Final = """AI 表格记录值格式（固定官方参考）：
- text：字符串。
- number：整数、浮点数或数字字符串。
- singleSelect：选项名字符串。
- multipleSelect：选项名字符串数组。
- date：毫秒时间戳或 ISO 8601 日期时间字符串。
- user：[{"unionId":"xxx"}]。
- department：[{"deptId":"xxx"}]。
- attachment：需先按钉钉官方附件上传流程取得附件值；本 Tool 不上传附件。
- unidirectionalLink / bidirectionalLink：{"linkedRecordIds":["record-id"]}。
- url：{"text":"显示文字","link":"https://example.com"}。"""


def notable_reference(content: str) -> dict[str, object]:
    return {
        "content": content,
        "source_version": NOTABLE_REFERENCE_SOURCE_VERSION,
        "trusted_reference": True,
    }
