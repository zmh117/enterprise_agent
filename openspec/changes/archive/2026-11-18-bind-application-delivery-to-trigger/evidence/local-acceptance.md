# 本地验证记录

日期：2026-11-06。

## 已确认

- 保存存在两个问题：管理请求缺少 `target_user_ids` 字段；最新版 Agent 目录未保留当前草稿固定的历史发布版本，导致原生必选下拉框显示空值。
- 新草稿的每条 Delivery 都通过自然入口身份关联 Trigger，发布使用 schema v7 和 `delivery_binding_mode=per_trigger`。v6 不可变发布仍保持原有规则。
- 165 项后端测试通过：业务应用控制面/路由、Webhook 接入与人员投递、可选鉴权、调试授权、钉钉治理/数据重建、渠道投递、工作区周期。HTTP 回归确认多人员、空人员保存，拒绝缺失/孤立/重复入口引用；运行回归确认多个 Webhook 不串用目标、顺序变化不影响路由。
- 13 项前端测试通过：每入口编辑、修改和删除关联、歧义旧投递提示、HTTP 回调替换、固定操作区的错误提示、Agent 与人员选择。
- Ruff、ESLint、Prettier、TypeScript/生产构建、OpenSpec strict validate 和 git diff --check 通过。构建保留既有 chunk 大小提示。
- 已重建并更新本地 api-server、admin-web、channel-dispatch-worker、webhook-worker；三个后端容器健康，两个入口 worker 确认包含 schema v7 代码，`/api/ready` 返回 HTTP 200 和 ready。
- 使用实际 `assist03 r63` 草稿，按新编辑器规则为两条钉钉入口关联原会话投递，经管理请求模型校验后调用实际保存服务，保存事务成功。随后主动回滚外层事务并复核：revision、draft ID、活动 deployment 均不变，当前仍为 r63；固定 Agent 已在 catalog 中可用。
- Chrome 独立标签页确认：当前草稿固定 Agent r48 可见且已选中；钉钉私聊、群聊各自显示“入口 → default-diagnostic-agent → 回复原会话”，保存按钮可用。截图核对卡片和固定操作区排版正常，核验标签页已关闭，用户原标签页保留。

## 验证边界

- 没有替用户持久保存草稿、发布或激活应用；事务验证已回滚。
- 没有调用真实 Webhook、执行 Agent 模型或发送钉钉/HTTP 消息。跨入口隔离与人员投递来自本地合成回归，不构成真实外部投递验收。
- 本次仅更新本地 Compose 服务；没有提交、推送或更新远程环境。

## 后续：Webhook 空列表与空入口校验

- 只读核对确认：`assist03 r63` 仍固定 Agent r48，该版本未绑定 Webhook；同一 Agent 的 r49 已绑定启用的“测试webhook”。原页面没有说明版本差异，未完成的第三个入口仍可提交空的 Connector 和路由引用。
- 补充明确的版本提示和手动切换入口；没有可用 Webhook、没有已绑定发布版本分别给出操作提示。未完成入口在页面阻止保存和新增投递，清空 Webhook 时同步清空路由引用。
- TypeScript 检查、17 项前端测试通过，覆盖显式切换版本、未完成第三个入口、仅保存结果、多人员投递以及空列表提示。新增测试的类型错误在首次 Docker 构建中发现，已修正并重新通过 TypeScript 检查。
- 用户随后确认“正常了”，本轮停止继续部署和浏览器核验。新增提示与校验尚未部署；未持久保存草稿、发布应用或发送消息。原计划的第三个 Webhook 保存事务核验未执行，不作为验收证据。

## 后续：聊天知识库授权失败的服务版本修复

- `job_6be29e525aa44c5894f5191f139b7825` 来自钉钉聊天，命中 `assist03` 和 Agent r49，业务应用使用 schema v7；用户启用且为 human，Job 与会话的应用发布引用、配置 hash 均一致，冻结授权包含 2 个知识库。
- 根因是上次只更新 API 和入口 worker，遗漏执行和知识服务。API 验证该发布快照成功，而旧 Agent Worker、Knowledge MCP 仍为 v6；旧 Worker 对同一快照校验失败，触发 `knowledge_job_denied`。不是知识库角色范围缺失。
- 更新前确认没有 PENDING、RUNNING 或 WAITING_APPROVAL Job。已重建并重建容器：两个 agent-worker 副本、knowledge-mcp、ones-mcp、dingtalk-mcp、external-action-worker、file-service、tool-mcp、job-dispatch-worker、delivery-dispatch-worker、file-worker、两个 file-processing-worker。它们使用共享业务应用授权代码，需与发布格式一起更新。API 和入口 worker 此前已为 v7；未更新模型、向量存储或 Python Runtime 容器。
- 119 项回归通过：`test_knowledge_job_access.py`、`test_knowledge_mcp_contract.py`、`test_knowledge_authorization.py`、`test_business_application_runtime_routing.py`。相关有健康检查的容器全部 healthy，两个 Agent Worker 均 running。
- 在 API、两个 Agent Worker 和 Knowledge MCP 中对失败 Job 做 PostgreSQL 只读事务诊断：仅在诊断进程的查询适配器中将这个 Job 的 RUNNING 查询条件替换为 FAILED，从而核对其余完整授权检查，全部通过且知识库交集仍为 2。未改数据库状态；正常门禁仍拒绝终态 Job。该结果证明发布与授权检查恢复，不代表重新执行了聊天。
- 未重放失败 Job、调用模型、查询业务正文或发送钉钉消息。用户需要发起新消息验证真实聊天；旧 Job 保留失败记录。本轮未提交或推送代码。
