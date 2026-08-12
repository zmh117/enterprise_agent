## 1. Agent 创建后端契约

- [x] 1.1 为 AgentConfigRepository 增加 Definition 与 r1 Draft 原子创建、按 code 查询和唯一冲突处理
- [x] 1.2 为 AgentConfigService 增加全局编辑授权、固定初始配置、Runtime 校验和创建审计
- [x] 1.3 增加严格创建请求模型、`POST /api/admin/agents` 和列表 `permissions.can_create`
- [x] 1.4 将 `agent_code_conflict` 投影为稳定 HTTP 409，并确保未声明平台控制字段被拒绝

## 2. 固定 Agent 幂等初始化

- [x] 2.1 实现固定 Python/TypeScript Agent bootstrapper，补齐缺失 Draft且不覆盖既有配置或 Publication
- [x] 2.2 增加 schema-head guarded `bootstrap_agents` CLI 并接入 Compose migrator 顺序
- [x] 2.3 增加 bootstrap 首次运行、重复运行、保留既有状态和 Runtime 漂移失败关闭测试

## 3. Agent 新建管理界面

- [x] 3.1 扩展前端 domain schema、API client 和 TanStack mutation，解析创建权限与创建结果
- [x] 3.2 在 Agent 列表增加空状态、“新建 Agent”按钮及编码、名称、说明、项目、Runtime 创建表单
- [x] 3.3 创建成功后刷新列表并进入 Agent 详情；失败时保留输入并展示结构化错误
- [x] 3.4 增加空列表、无权限、Python 创建、TypeScript 创建和失败保留表单的组件/API 测试

## 4. 回归与运行验收

- [x] 4.1 增加后端 API/service/repository 测试，覆盖权限拒绝、非法字段、非法 Runtime、重复和并发 code
- [x] 4.2 运行相关后端测试、Ruff、前端测试、typecheck/build、OpenSpec strict validation 与 git diff check
- [x] 4.3 重建并运行 migrator，验证当前空库幂等出现两个固定 Agent、API readiness 和新建后无 Publication
