## 1. 协议与数据模型

- [x] 1.1 新增 Runtime protocol v1.5、`audit_chunk`/terminal 完整性合同、generated contract 与历史兼容测试
- [x] 1.2 新增 migration 124 和 invocation 级完整审计仓储，覆盖幂等、冲突、SQLite/PostgreSQL 与 schema facts

## 2. Runtime 与 Worker

- [x] 2.1 实现 Python Runtime `RunAuditRecorder`，保存完整上下文、SDK 消息、工具 I/O、usage 和隔离 raw API body
- [x] 2.2 将审计分块写入 Runtime stream，并在 Worker 验证重组；成功和失败结果都携带审计
- [x] 2.3 在 AgentExecutor 成功、失败、超时和重试路径幂等持久化审计

## 3. 管理 API 与 Web

- [x] 3.1 管理 Job 详情在 scope 检查后加载完整审计，Debug/Tool/MCP 查询保持安全摘要
- [x] 3.2 扩展前端 schema/API，在现有详情中增加调优摘要和四组默认折叠的完整正文
- [x] 3.3 覆盖历史空态、多 attempt、超长内容、授权失败和范围外不读取正文

## 4. 验证

- [x] 4.1 运行协议、Runtime、Worker、仓储、管理 API 和前端聚焦测试
- [x] 4.2 运行 Ruff、mypy 变更路径、ESLint、TypeScript、build、Compose config、strict OpenSpec 和 diff check（mypy 仍报告 one_runtime 既有类型基线问题，本变更新增文件通过）
- [x] 4.3 使用真实浏览器验证摘要布局、默认折叠和长内容滚动
