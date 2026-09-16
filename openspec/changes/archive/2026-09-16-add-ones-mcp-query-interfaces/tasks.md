## 1. Provider 契约基础

- [x] 1.1 建立 ONES Tool 输入契约的单一代码事实源，并让服务端 contracts 与平台 Manifest 共同使用
- [x] 1.2 扩展 Provider HTTP Client 支持代码固定的结构化 query 参数，同时保持任意 path query、URL、代理、重定向和大小边界拒绝
- [x] 1.3 扩展 GraphQL Operation/Client 支持默认 Team 路径模板、固定查询类型和有界审计请求摘要

## 2. GraphQL 与 REST Operations

- [x] 2.1 将项目、工作项类型、通用/迭代工作项和详情 GraphQL 文档集中加入 documents 并实现变量构造与规范化 Parser
- [x] 2.2 将测试库、模块、计划、用例列表和用例详情 GraphQL 文档集中加入 documents 并实现变量构造与规范化 Parser
- [x] 2.3 实现迭代列表、工作项时间线和 Team 人员搜索 REST Operation，保留项目角色成员精确两步调用

## 3. MCP Tool 与治理装配

- [x] 3.1 提取共享只读 ONES Tool 执行骨架，统一 Principal、审计、一次 refresh、Credential 使用和安全错误处理
- [x] 3.2 实现项目、迭代、工作项类型、工作项查询/详情/时间线和 Team 人员 Tool
- [x] 3.3 实现测试库、模块、计划、用例查询和用例详情 Tool
- [x] 3.4 将新增 Tool 接入 registry、bootstrap 和 MCP Tool Manifest，并保持现有工作项搜索 Schema 与既有实现不变

## 4. 合成 Mock 与回归测试

- [x] 4.1 扩展独立 ONES Mock 的合成项目、迭代、消息、人员和测试资产 fixture 及精确 GraphQL/REST 路由
- [x] 4.2 增加 HTTP query、GraphQL/REST Operation、Parser 边界和敏感字段排除测试
- [x] 4.3 增加 Tool 输入、Principal/refresh/审计、Manifest/schema hash、Publication/Job 和 MCP Runtime 回归测试
- [x] 4.4 增加架构测试，保证生产与测试代码不读取 `ones_mock/ones/` 且新增 Tool 仍为固定只读业务能力

## 5. 验证与交付

- [x] 5.1 运行 ONES 聚焦 pytest、Ruff、mypy/compileall、OpenSpec strict validation 和 `git diff --check`
- [x] 5.2 运行两份 Compose config 校验，重建并启动 `ones-mcp` 与独立 Mock，验证健康检查和合成接口闭环
- [x] 5.3 记录实现验证证据，明确 Mock 通过不等于真实 ONES 兼容，真实环境只读探测保持待办
