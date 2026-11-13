"""Business presentation does not discard backend evidence or widen authorization."""

from dataclasses import replace

import pytest

from app.modules.agent.domain.runtime import AgentExecutionContext
from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.python_runtime.claude_client import build_system_prompt
from app.shared.code_answer_presentation import strip_code_answer_references
from app.shared.code_answer_tool_contracts import CODE_ANSWER_PRESENTATION_INSTRUCTIONS


@pytest.mark.parametrize("with_skill", [False, True])
@pytest.mark.parametrize("source_bound", [False, True])
def test_business_rules_reach_discovery_and_source_analysis(with_skill, source_bound):
    loader = SkillLoader()
    names = ("code-business-query",) if with_skill else ()
    snapshot = {"skills": list(names), "versioned_skills": loader.freeze_versioned(names)}
    context = AgentExecutionContext(
        system_role="业务助手",
        safety_rules=[],
        user_question="环境 prod，SVN r100：怎样配置数值控件，让完成件数显示输入值？",
        project_code="synthetic-project",
        allowed_tools=[],
        tool_restrictions=[],
        skills=loader.load_publication(snapshot),
        retrieved_context={"code_source": {"sources": []}} if source_bound else {},
        conversation_summary="",
        effective_tool_names=("mcp__knowledge_mcp__knowledge_search",),
    )
    prompt = build_system_prompt(context)
    assert CODE_ANSWER_PRESENTATION_INSTRUCTIONS in prompt
    assert "Cite actually used answers as code-answer:" not in prompt
    assert "证据位置与未知项" not in prompt
    assert "旧知识答案也须重述为业务解释" in prompt
    assert "不猜状态中文名称" in prompt
    assert "当前授权允许" in prompt
    assert "前端配置、实际显示文案、配置保存、执行产值与目标页面取值链" in prompt
    assert "不能仅凭后端字段推断" in prompt
    assert "作为 critical 未知保留 partial" in prompt
    assert "只有后端逻辑不能扩写成界面指南" in prompt
    if with_skill:
        frozen = snapshot["versioned_skills"]["code-business-query"]["content"]
        assert frozen in prompt
        assert "前端配置 → 执行产值 → 目标页面取值" in frozen
        assert "输入框没有标签时" in frozen
    if source_bound:
        assert CODE_ANSWER_PRESENTATION_INSTRUCTIONS in build_system_prompt(
            replace(context, effective_tool_names=())
        )


@pytest.mark.parametrize(
    "name",
    ["knowledge_search", "knowledge_get_code_answer", "knowledge_save_code_answer"],
)
def test_published_tools_carry_the_same_business_presentation_contract(name):
    assert CODE_ANSWER_PRESENTATION_INSTRUCTIONS in MCP_TOOL_MANIFEST[name].description


@pytest.mark.parametrize(
    "visible",
    [
        (
            "环境 prod，SVN r100。\n\n"
            "- 选择子批次后，命中限制状态时不能进入拆分编辑。\n"
            "- 该状态的中文名称尚未确认；最终提交的限制也未核验。\n\n"
            "<!-- ordinary document comment -->"
        ),
        (
            "环境 prod，SVN r100，以下为合成操作示例。\n\n"
            "1. 在数值控件配置页，变量填写 `@reading@`。\n"
            "2. 勾选「记录为汇总值」，在其下方输入框填写 **完成件数**。\n"
            "3. 执行控件并输入 37；打开汇总页，完成件数显示 37。\n\n"
            "37 是示例输入，不是默认值；配置页上级菜单入口尚未确认。"
        ),
    ],
)
def test_internal_reference_removal_preserves_business_conditions_and_other_markdown(visible):
    internal = visible + (
        "\n\n<!-- code-answer:document-1@revision-1 -->\n<!-- code-answer:document-2@revision-2 -->"
    )
    assert strip_code_answer_references(internal) == visible
    assert strip_code_answer_references(visible) == visible
