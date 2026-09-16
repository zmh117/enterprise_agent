## Why

当前文档处理链路把 File Processing Worker、Docling 本地执行 Worker 和 Profile 全局 Docling 并发都固定为 1，十个受支持附件只能串行完成。需要在不引入 Redis/RQ/Ray、不横向扩展本地状态 Docling 容器、也不削弱 processing run 幂等与不可变 Profile 边界的前提下，将单部署的受控并发提升到 2。

## What Changes

- 将固定文档处理拓扑调整为两个 `file-processing-worker` 实例，共享一个 `docling-serve` 服务；单个 Docling 容器内部固定两个 local execution workers。
- 将 `docling-layout-ocr-v2` 的全局 Docling 并发上限和单 parent 图片并发上限调整为 2，并通过 PostgreSQL 协调的有界 admission/lease 保证滚动重建或实例漂移时仍不会超过上限。
- 保持每个父文件、内嵌图片和 assembly 使用既有独立 RabbitMQ 消息与原子 claim；不把多个用户文件合并为一个 Docling 请求。
- 禁止在 local engine 与 single-use result 模式下直接运行多个 `docling-serve` 容器，避免 submit、poll、fetch 命中不同实例。
- 增加聚合 Worker readiness、并发槽位诊断、过期 lease 恢复和并发 10 文件验收；容器 healthy 不作为业务并发验收。
- **BREAKING**：并发限制属于不可变 Profile payload，当前 Profile hash 将变化。旧 Publication 和历史终态 run 保持不可变、只读可见且不得原地改写；旧 hash 的非终态 run 必须在切换前排空，新 Revision 必须按新 hash 重新发布并激活。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `document-file-processing`：把单部署 Docling 全局并发从 1 提升为严格上限 2，并定义跨 Worker admission、恢复、幂等和单文件请求边界。
- `platform-operations`：定义两个 File Processing Worker 加单个双 local-worker Docling 的 Compose 拓扑、资源与聚合就绪约束，并禁止本地状态 Docling 的无粘性多副本。
- `business-application`：定义 Profile hash 切换时旧 Publication 的只读可管理状态、非终态 run 排空和新 Revision 重新发布/激活边界。

## Impact

- 影响 `file-processing-worker` RabbitMQ consumer、File Service processing claim/admission、Docling Provider、processing repository/migration、readiness/运维诊断和 Compose 部署。
- 影响 `docling-layout-ocr-v2` Profile hash、Business Application catalog/Publication 状态及部署切换流程，但不改变支持格式、Docling 请求内容、Representation schema、原件身份或 Agent Sandbox 协议。
- 不新增 Redis、RQ、Ray、外部调度器、任意 Docling URL、第二个 Docling 容器、Agent 可见二进制或新的 MCP Tool。
