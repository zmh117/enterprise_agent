# 本地修复与验证记录

日期：2026-11-13。范围：当前工作区代码、合成数据库/SDK/MCP 请求。未访问真实业务消息、未连接现场模型进行问答、未部署、未改写旧 Job 或 Qdrant 数据。用户提供的现场数量与两条 Job 故障诊断未独立重查。

## 已实现

- 成功代码检索 query 在 Runtime invocation 内保留；成功准入返回 analysis_id 后绑定。保存时宿主填入规范问题；不同知识库、环境、版本和 analysis 的错误关联仍拒绝，服务端 hash 与证据门槛保留。
- 有源码 grant 且未完成保存时，Stop hook 最多发出一次保存纠正。没有剩余预算、已保存、仅命中缓存或授权不可用不触发。partial/conflicted 可保存但不索引。
- 纠正期间耗尽时间、工具次数或模型轮次时保留先前业务回答；用户取消和无法核验轮次的合同错误继续失败，不借补保存吞掉这些错误。
- Knowledge MCP 安全请求摘要增加 analysis_id；标准收尾按明确关联在分析 report_json.knowledge_save 中记录保存服务结果。晚落库不按时间错配；旧缺关联调用标为 unconfirmed。本地 SDK 参数拒绝仍在 Runtime 审计查看。
- Runtime 提示模板升级到 agent-system-prompt-v21，Skill 与运行说明同步补充。

## 本地验证

以下批次存在重叠，测试数量不能相加为唯一用例总数。

| 验证范围 | 结果 |
| --- | --- |
| 新增 test_code_answer_finalization：问题改写后实际保存、证据拒绝、幂等重放、实际 bridge 发出的规范问题、SDK Stop hook、预算/取消/不可核验错误、保存结果与索引区分 | 最终 18 passed |
| test_code_answer_finalization、test_code_source_runtime_v2、test_knowledge_save_diagnostics、test_code_result_recorder、test_knowledge_mcp_server | 101 passed；随后增加的不可核验轮次用例由上述最终 18 项覆盖 |
| Python Runtime、知识派发、答案保存/索引、原 Job 桥、轮次预算、架构与测试分层 | 248 passed |
| 提示模板 v21 后的 test_python_agent_runtime、test_agent_runtime_protocol_contract、test_mcp_tool_runtime | 214 passed |
| 受影响代码与测试 Ruff 检查、13 个文件格式检查 | 通过 |
| 9 个受影响源文件 mypy strict | 通过 |
| git diff --check | 通过 |
| openspec validate fix-code-answer-save-finalization --strict | 通过 |

原有未提交的源码读取与敏感阻断修改保留。本 change 未提交、未归档；canonical specs 未通过本次工作流同步，行为增量保留在本 change 的 delta 中。

## 部署与现场验收待办

协调更新 API/agent-worker、knowledge-mcp 和两个 Python Runtime，使 Worker/Runtime 的提示模板均为 v21；更新发布绑定的 Skill 后使用新 Job。无需数据库迁移、清空现有答案或重建 Qdrant。

在用户明确的环境和 SVN 版本重新提交两问：检查保存回执、analysis 的 knowledge_save、supported 答案及 code_index_task，再核对知识检索可用性。不得用问题条数直接要求 Qdrant point 数相等，不得把旧聊天正文直接改成 supported。现场真实模型/SVN/PostgreSQL/Qdrant 全链路验收仍未完成。
