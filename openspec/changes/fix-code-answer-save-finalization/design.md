## Context

成功检索的普通审计只保存问题 hash，源码 analysis 通过 search_id 绑定该 hash。Runtime 已拥有该次请求与成功响应，且源码分析只能在原 invocation 内进行；不需要增加持久化问题表或读取完整审计正文。

## Goals / Non-Goals

目标是消除模型重填问题导致的保存拒绝，并在同一任务中补足一次保存机会，保留独立、可排查的保存结果。不会把回答成功等同于知识就绪，不降低 supported 的证据门槛，不为旧任务伪造证据或后台继续模型分析。

## Decisions

1. Runtime 源码宿主在内存保留成功代码检索的规范 query，按返回 search_id 关联；成功 SVN 准入再绑定 analysis_id。save 的 question 由宿主从该绑定填入，服务端仍核验 question_hash。失败检索、其他 analysis、缺失绑定均不能成为保存问题；重放使用同一规范文本。内容不写普通审计/日志，invocation 结束后丢弃。
2. 源码 Job 的 Stop hook 在已取得 grant、尚未成功保存且预算允许时，仅阻止结束一次，请同一 Agent 提交 supported/partial/conflicted 结果。第二次结束放行；不增加原工具次数、轮次、时间上限。已保存、仅命中缓存、未取得源码 grant、预算耗尽、身份/权限故障不追加模型回合。
3. Knowledge MCP 的保存请求安全摘要只增加 analysis_id，不保存问题或结果正文。原结果事务按该明确关联在 code_analysis.report_json 的独立 knowledge_save 对象写入固定状态、保存服务收到的尝试次数、安全错误码；不按审计落库时间猜测所属分析。没有关联信息的旧调用标为 unconfirmed；本地 SDK 参数拒绝继续由既有 Runtime 审计定位，不冒充已提交保存服务的尝试。保存失败不拒绝业务回答，partial/conflicted 保持不索引。
4. 保留现有公开 save 输入形状和服务端 hash 防线，避免更新冻结工具合同。补充工具说明及提示，宿主实现承担可靠绑定和收尾。

## Risks / Trade-offs

- 进程结束后不能恢复瞬时问题绑定 → 原 invocation 停止并按现有规则释放占用；新任务重新检索，不读取历史正文恢复旧保存。
- SDK Stop hook 未触发或模型仍未保存 → 后台保存结果仍记录未尝试/失败；不宣称模型真实验收成功。
- 补保存可能遇到预算或授权失效 → 使用现有预算和当前授权，不重启模型、不伪造 supported。
- 用户提供的两条现场诊断未重新查询 → 仅作为故障线索，本地验证用合成问题和证据；真实环境待新任务验收。

## Migration Plan

无数据库 migration、无 Qdrant 重建。部署需重建 API/agent-worker（标准结果记录的部署消费者）、knowledge-mcp（保存关联摘要）和两个 Python Runtime（绑定与 Stop hook）；如更新已发布 Skill，重新发布后用新 Job 验收。先保留现有知识；旧失败问答须在对应环境/SVN 版本重新核验和保存。

提示模板同步升级到 agent-system-prompt-v21，Worker 和 Runtime 必须一起更新，新 Job 使用新冻结请求；不改写旧 Job。

## Open Questions

无规格待确认项。用户已选择保存失败仍保留业务回答，并在原预算内补做一次保存。
