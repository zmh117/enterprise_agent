## 1. 合同与数据模型

- [x] 1.1 扩展代码 Tool Manifest，加入 effect/confirmation policy 并为未来 ONES mutation 增加 fail-closed 校验
- [x] 1.2 新增 Action Intent、Card Outbox 与执行 claim 的 migration 和 SQLite/PostgreSQL 兼容约束
- [x] 1.3 实现 Action Intent domain、repository、状态机、幂等键和有界序列化

## 2. dingtalk-mcp MVP

- [x] 2.1 创建固定 `dingtalk-mcp` Streamable HTTP Server 骨架、安全中间件和健康检查
- [x] 2.2 实现 DingTalk Principal 解析，绑定当前 Job、来源 Connector、企业、staff ID 与 union ID
- [x] 2.3 实现 `dingtalk_create_todo` 输入校验、确认意图准备和统一 MCP 审计
- [x] 2.4 实现固定 DingTalk Access Token、互动卡片与创建待办 Provider clients，限制 host/path/body/响应

## 3. 卡片确认与执行链

- [x] 3.1 为 `dingtalk-runtime` 注册卡片 topic、规范化有限字段并转交控制 API
- [x] 3.2 新增内部卡片 action API，校验 lease、Connector、actor、token、revision 和状态并返回快速 ACK
- [x] 3.3 实现 Card Outbox claim/投放/更新与恢复逻辑，固定模板 ID、outTrackId 和禁止转发
- [x] 3.4 实现已批准 Action Intent claim、执行前重新授权、待办 Provider 调用和终态卡片更新
- [x] 3.5 对 reject、duplicate、expired、wrong actor、revision mismatch 和 revise-not-supported 实现失败关闭

## 4. 发布与部署接入

- [x] 4.1 将 `dingtalk-mcp` server policy、Tool contracts、Agent/Application/Job snapshot 和 Runtime token projection 接入固定治理链
- [x] 4.2 更新角色 Tool 目录，允许且仅允许确认策略完整的业务 mutation Tool
- [x] 4.3 增加 Docker image target、Compose 服务、worker、环境占位符、健康检查和启动依赖
- [x] 4.4 补充 dingtalk-mcp README、MVP 运维前置条件和分阶段升级计划

## 5. 验证

- [x] 5.1 增加 Manifest/Principal/MCP Tool/Provider contract 单元与 contract 测试
- [x] 5.2 增加 Action Intent 状态机、卡片 callback、重复点击、撤权和 worker recovery 测试
- [x] 5.3 增加 dingtalk-runtime TypeScript 测试与 Compose/security 拓扑测试
- [x] 5.4 运行相关 pytest/npm test、ruff/mypy 定向检查、migration smoke、Compose config、OpenSpec strict validate 与 git diff check
- [ ] 5.5 在具备测试 Connector 权限后执行真实 Job→卡片→同意/拒绝→待办→卡片结果 E2E，并记录不含 Secret 的证据
