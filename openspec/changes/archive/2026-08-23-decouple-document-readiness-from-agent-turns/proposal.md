## Why

当前非空文字会无条件认领会话工作区里全部未消费附件；只要其中任一文档可读表示仍为 `PENDING`，Job 就停在 `WAITING_INPUT`，连与文件无关的问题也被挡住，用户看到的是 Agent 失败或整轮卡住。文档处理已经在独立 `file-processing-worker` 上运行，缺的是按**单条消息**绑定精确 `file_version` 和所需能力，而不是把整个工作区或一次 Agent Job 绑定到 Docling。

## What Changes

- 废除「第一条后续文字原子认领全部未消费附件」作为自动物化规则；改为每条非空文字独立解析本轮依赖的精确文件版本与能力。
- 引入确定性 File Context Resolver（当前消息附件 → 钉钉引用/回复 → 工作区精确文件名 → 近指代且唯一最近活动文件）。**不上**隐式意图分类器；无硬证据则不绑文件。
- 本轮依赖收成三种能力：`METADATA`、`ORIGINAL`、`READABLE_CONTENT`。只有 `READABLE_CONTENT` 才要求 Markdown 表示就绪。
- **BREAKING（准入语义）**：需要 `READABLE_CONTENT` 且表示未就绪或处理失败时，系统用固定中文说明结束本轮，**不创建或不释放 Agent Job 到 `agent.jobs`**，不调用模型。不得再用 `WAITING_INPUT` 等待 Docling。
- 与本轮无关的文字立刻创建 Agent Job；Manifest 不自动物化处理中的文档，工作区允许同时存在 READY / PROCESSING / FAILED 的不同版本。
- `WAITING_INPUT` 仅保留给**本轮已绑定附件的来源下载/导入**；来源终态后重新走能力门禁，而不是继续等表示。
- File MCP 作为第二道闸：物化未就绪或失败时返回稳定错误码；系统提示禁止臆造正文。`list_files` / `file_get_metadata` 可暴露有界处理状态，不得返回正文、对象键或 Docling 内部标识。
- 曾因未就绪被挡的轮次，在表示就绪后可向原会话发一次通知；**不自动重放**原问题。
- 本变更覆盖仍在进行中的 `add-governed-docling-file-representations` 里「认领文档后 Job 保持 `WAITING_INPUT` 直到表示终态」的准入条款；不重做 Docling 管线、Manifest v4、原件/表示分离或 Compose 拓扑。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `channel-conversation`: 将纯附件暂存后的文字触发从「认领全部未消费附件」改为「按本轮确定性绑定认领」；钉钉引用必须能解析到被引消息上的文件版本；未就绪/失败/歧义走系统说明而非 Agent 失败 JSON。
- `execution-delivery`: Agent Job 不再因 Docling 或 `file_processing_run` 非终态而等待；门禁未过不入 `agent.jobs`；曾被挡轮次可通知、不重放。
- `task-file-workspace`: Job File Manifest 只自动物化本轮绑定且能力已就绪的精确版本/表示；处理中版本可以工作区候选存在，但不得因工作区里有 PENDING 文档而拒绝创建无关 Job。
- `builtin-tool-resource`: File MCP 对未就绪/失败表示返回结构化错误码，并禁止把处理中文档当成可物化正文。

## Impact

- 受影响代码主要在 `CreateAgentJobService`、`claim_staged_attachments`、渠道入站（把 `originalMsgId` 传入 Job 命令）、附件释放（`_release_if_ready` 不再因 `readability_status=PENDING` 卡住无关或已过门禁的 Job）、Manifest 自动物化集合、File MCP `file_prepare_materialization` / 列表与元数据、Agent 文件提示词，以及一条窄的被挡轮次事实（通知用）。
- 需要前向 migration：被挡轮次记录、消息上的引用目标（若现有 `safe_metadata` / `external_message_id` 不足以稳定反查），不新增第二套文件表家族，不新增编排进程或队列。
- 钉钉投递：门禁说明和就绪通知走现有 sessionWebhook Markdown 路径，文案为固定中文，不得再走 `failure_notification` JSON（避免 `agent_runtime_error`）。
- 测试：合成会话覆盖「处理中问无关问题」「处理中问内容」「引用绑定」「文件名绑定」「近指代歧义」「元数据/原件不挡」「MCP 未就绪」「就绪通知不重放」；并修正仍断言「后续文字认领全部暂存附件并 WAITING_INPUT 等 Docling」的用例。
- 与 `add-governed-docling-file-representations` 并行时，本变更为准入语义的权威来源；apply 前须改写该 change 中尚未完成的「Job 等表示」任务，避免两套 delta 在 sync 时互相覆盖。
