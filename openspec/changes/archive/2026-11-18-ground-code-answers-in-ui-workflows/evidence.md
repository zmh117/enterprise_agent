# 本地验证记录

日期：2026-11-13。仅本地代码与合成回归，未部署、未调用真实模型或业务 SVN，未改写知识库答案。

## 已确认的实现

- 共享代码问答约束进入知识工具描述、知识发现提示和源码分析提示；配置/操作回答需要前端配置、执行赋值及下游读取证据，缺关键环节保留 partial。
- 发布 Skill 包含详细的页面/文案定位、配置保存、执行写值、页面回填与历史答案覆盖检查。沿用现有 claims/coverage/unknowns 和实际 Read 证据，不新增能力或存储模型。
- Prompt 版本为 `agent-system-prompt-v22`。原有保存收尾、环境/版本授权与引用关联规则保留。

## 验证结果

- `.venv/bin/pytest -q backend/tests/test_code_answer_presentation.py backend/tests/test_python_agent_runtime.py backend/tests/test_agent_runtime_protocol_contract.py backend/tests/test_mcp_tool_runtime.py`：223 passed（45.03 秒）。覆盖有/无版本化 Skill、有/无源码能力的规则传播、工具描述一致性及业务步骤/输入字面值在内部引用移除后的保留，并回归 Runtime 与工具合同。
- Ruff check / format --check：4 个变更 Python 文件通过。
- mypy：2 个变更源文件通过。
- `openspec validate ground-code-answers-in-ui-workflows --strict` 与 `git diff --check` 通过。

这些断言检查规则接线、发布内容加载和文本保留，不证明模型已准确识别任何真实业务链。测试中的页面名、字段名和输入值均为合成示例，不是生产规则。

## 待真实环境验收

1. 协调更新 Prompt/工具合同消费者与两个 Runtime；重新发布版本化 Skill、更新业务应用绑定，以新 Job 检查 v22 与新 Skill 生效。不能只重启旧镜像或复用冻结任务。
2. 使用受控的前端配置到下游页面取值案例，核对回答是否准确列出页面、可见控件、必要填写文字、执行动作和结果；后台证据应分别覆盖配置保存、执行写值与目标页面回填，不能只有最终后端读取函数。
3. 追问同版本旧答案未覆盖的配置操作，验证模型补查所需界面/执行证据；已有完整操作证据时应直接复用。
4. 在必要前端证据不可用的案例中，确认回答不推测控件或刷新步骤，关键 unknowns 与 partial 一致；纯后端范围的已核验 claim 不被误判为必须读取全 UI。
5. 检查本次保存结果及索引状态，只有满足现有 supported 准入的答案可进入确定知识。用户纠正或历史回复文本不得直接替代源码证据。

任务 3.1 保持未完成；本记录不代表目标环境部署或真实模型验收通过。
