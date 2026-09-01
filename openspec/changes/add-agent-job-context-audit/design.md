## Context

`one_runtime` 已把 Claude Agent SDK 放入独立 Python Runtime，并通过严格的 Runtime v1.4 NDJSON 协议把安全归一化事件传给 Worker。现有 `agent_job_execution_summary`、`agent_model_call`、`agent_tool_call` 和 `mcp_operation_audit` 适合筛选与安全运维，但设计上明确排除完整 Prompt、raw SDK message、模型完整回复和原始工具载荷。

用户确认完整正文不脱敏。实现必须尊重当前跨进程、恢复账本、Job tool snapshot 和业务范围授权，不能把已退役的 Worker 内直连 Claude 客户端重新引入，也不能修改已经发布的 v1.4 schema 或复用 migration 034。

## Goals / Non-Goals

**Goals:**

- 保存模型实际可见的完整应用上下文、SDK 消息、API request/response 与工具输入输出。
- 提供请求次数、峰值上下文、Token/cache/cost、注册/加载/调用工具数等调优摘要。
- 成功、失败、超时、重试和相同 invocation 恢复重放均可审计且幂等。
- 完整正文只在管理端通过 Job scope 后读取，页面摘要优先、正文默认折叠。

**Non-Goals:**

- 不新增 Collector、Trace 平台、对象存储旁路或独立审计服务。
- 不主动把 API Key、Auth Token、Secret ref、Runtime Grant、Principal JWT 或 HTTP 认证 Header 复制进审计。
- 不恢复 Provider/Claude Code 未返回的 hidden reasoning。
- 不改变既有上下文预算；若来源在进入模型前已截断，只保存实际进入模型的内容并保留截断事实。

## Decisions

### 1. 新建 Runtime v1.5，不原地修改 v1.4

v1.5 在 v1.4 基础上新增 `audit_chunk` 事件。Runtime 将完整审计对象序列化为 UTF-8 JSON，计算 SHA-256，再以 40 KiB 原始字节分块并 Base64 编码。每块携带 `chunk_index`、`chunk_count`、`sha256`、`encoding` 和 `content`；terminal 携带同一 `audit_sha256` 与 `audit_chunk_count`。Worker 必须验证连续索引、总数、摘要和 JSON 对象类型，任一不一致都按 Runtime 协议错误失败。

40 KiB 分块使单条 NDJSON 保持在现有 64 KiB 行边界内。v1.5 将总 stream 边界提高到与 SDK 64 MiB buffer 相匹配的有界值；应用不对边界内正文再做内容截断。`audit_chunk` 只用于传输：Runtime 恢复账本保存它以支持相同 invocation 重放，Worker 重组后不把 Base64 块复制进 `agent_runtime_event`。

### 2. Python Runtime 以独立 Recorder 采集完整审计

`RunAuditRecorder` 在上下文准备完成后固化：

- 精确 System Prompt、User Prompt、上下文来源和安全 provenance；
- effective Tool 名称、MCP binding/schema hash，以及 init/raw request 中实际工具定义；
- SDK 返回的 System/Assistant/User/Result message 完整 JSON 化值；
- Tool use/result block 的完整模型可见输入输出；
- attempt 隔离目录中的全部 `.request.json` / `.response.json`；
- Result usage/model usage/cost 与逐轮 usage，以及独立的注册、加载、自动批准、调用和不同工具口径。

未知 SDK 类型依次使用 dataclass、`model_dump`、`to_dict`、`__dict__` 和 `str()` 转成 JSON，不按长度裁切。安全 Tool/MCP 主账仍使用现有归一化器，不因完整审计改变。

### 3. 新表按 invocation 幂等，Job 汇总复用现有主账

migration 124 新增 `agent_run_audit`，以 `(job_id, invocation_id)` 唯一，保存 attempt 编号、状态、完整 JSON/TEXT 正文、typed 调优摘要、错误和时间。相同 Runtime invocation 的恢复重放只接受内容一致的审计；冲突内容 fail closed。

不向 `agent_job` 增加统计列。详情页从 attempt 审计聚合峰值上下文和工具指标，并继续使用 `agent_job_execution_summary` 作为 Token、耗时、模型 usage 与成本的 canonical Job 汇总。

### 4. 成功和异常使用同一持久化入口

`AgentRunResult` 增加 `run_audit`。Runtime 失败 terminal 在 Worker 重组完整审计后，把它附加到 typed exception；`AgentExecutor` 在成功和异常分支都调用同一 repository 方法。审计必须在 Job 成功落库或失败/重试处理完成前持久化；持久化失败不能伪装成模型成功。

### 5. 授权检查先于大正文读取

`GET /api/admin/jobs/{job_id}` 先读取不含完整审计的 Job evidence，执行既有 `jobs.read` 与 `AdminScope` 判断，通过后才单独查询 `agent_run_audit`。范围外查询返回 404，且 repository 不读取大正文。Debug evidence、Tool Call 和 MCP 查询不返回完整审计。

### 6. 页面在现有运行详情上增加四组折叠区

保留现有执行汇总、Tool contract、文件、Delivery 和模型轮次，不用旧页面整文件覆盖。新增 Context tuning 摘要，并按 attempt 显示四个默认关闭的 `<details>`：上下文与 Prompt、模型 request/response、完整工具执行、usage 与元数据。`pre` 使用固定最大高度、换行和滚动；历史 Job 显示明确空态。

## Risks / Trade-offs

- [正文显著增大] → 仅详情按授权读取；分块传输和 SDK buffer 采用显式上限，列表不读取正文。
- [Runtime 协议升级复杂] → v1.5 expand-first，Worker/contract 测试先落地，不原地修改 v1.4。
- [完整正文包含企业敏感数据] → 用户已确认不脱敏；仍阻止运行凭据主动进入审计，并先鉴权后查询正文。
- [Runtime 强杀前无法形成完整 terminal] → 同 invocation 恢复账本可重放已提交事件；未形成可验证审计时明确显示缺失，不伪造。
- [hidden thinking 不可恢复] → 保存 SDK 实际返回值并在 UI 标明上游限制。

## Migration Plan

1. 应用 migration 124 和支持 v1.5 的 Worker/管理 API；旧 v1.4 Job 继续可读。
2. 发布带 v1.5 Recorder/分块事件的 Python Runtime，再切换新的 Agent Publication。
3. 部署 Web，并用 Fake SDK 覆盖成功、失败、超时、多轮 Tool Loop、超长折叠和授权范围。
4. 回滚时先停止新 Publication；保留新表与 Worker 双读，不删除已采集正文。
