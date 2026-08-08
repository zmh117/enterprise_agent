## 1. 契约基线与失败复现

- [x] 1.1 增加后端回归测试，复现“保存连接成功后立即配置 Key 使用旧 expected revision 返回 409”的现有三段式竞态
- [x] 1.2 增加前端回归测试，证明当前连接查询刷新窗口会把过期 revision 传入 Credential Sheet
- [x] 1.3 定义 discover、test-draft、configure 的严格请求/响应 schema、Credential 来源枚举和稳定错误码，并拒绝额外字段
- [x] 1.4 记录实现前数据库基线，只检查模型连接 revision/status 与 Secret 绑定状态，不读取任何 Secret 明文或密文

## 2. DeepSeek官方模型发现

- [x] 2.1 实现 DeepSeek Anthropic Base URL 规范化及 `/anthropic` 到 `/models` 的确定性派生
- [x] 2.2 复用并收紧 HTTPS、host allowlist、443 端口、userinfo、query、fragment、DNS/IP 和 redirect 防护
- [x] 2.3 实现受限 DeepSeek 模型发现客户端，使用 Bearer Credential 并限制超时、响应体 256 KiB、模型数 200 和模型 ID 长度 200
- [x] 2.4 实现模型列表 JSON 校验、去重、稳定排序和安全公共投影，不返回上游正文或 header
- [x] 2.5 增加模型发现单元测试，覆盖官方 URL、带前缀 path、非法 suffix、第三方 host、非 443 端口、私网 DNS、redirect、401、超时、畸形/空/超限响应

## 3. 临时Credential与草稿配置测试

- [x] 3.1 实现“本次提交 API Key”与“沿用当前有效 Credential”互斥解析，缺失、停用、不可解析或 rotation-required 绑定必须要求新 Key
- [x] 3.2 构造不持久化的临时 ModelRuntimeBinding，并复用现有 Claude Agent SDK tester 执行无 Tool、无 MCP、单轮、短超时探测
- [x] 3.3 确保 discover 与 test-draft 的外部 I/O 不进入数据库 unit of work，失败前后 Secret、Secret version、连接 revision、Agent 草稿和 Publication 数量不变
- [x] 3.4 实现模型映射规范化，主模型必选，Opus/Sonnet/Haiku/Subagent 继承主模型，并校验所有显式模型属于当前发现结果
- [x] 3.5 增加草稿测试，覆盖新 Key、沿用现有 Key、发现成功但 SDK 失败、模型不可用、映射继承、超时与错误脱敏

## 4. 原子模型连接配置服务

- [x] 4.1 实现 configure 的外部 I/O 前 expected revision 预检，以及发现和 SDK 测试后的二次 revision 校验
- [x] 4.2 在同一数据库 unit of work 中实现 Secret 创建或轮换、ready 连接 revision 追加、current revision/status 更新和脱敏审计
- [x] 4.3 实现首次创建、沿用有效 Credential、主动轮换、缺失绑定恢复和 disabled Secret 恢复语义
- [x] 4.4 为确定性 Secret code 增加 model connection 所有权 metadata 校验，匹配时允许安全重新绑定，不匹配时返回 credential_ownership_conflict
- [x] 4.5 确保任何模型发现、SDK 测试、Secret 操作、审计或 revision 冲突失败都完整回滚，API 不得在数据已提交后返回 500
- [x] 4.6 增加服务层事务与并发测试，覆盖首次配置、沿用、轮换、孤立 Secret、所有权冲突、测试后并发修改和所有失败无部分写入
- [x] 4.7 增加 Secret 泄漏门禁，搜索请求、响应、错误、日志、审计和数据库非 Secret 字段，确认无 API Key、Authorization header 或 SDK stderr 原文

## 5. 管理API、授权、限流与旧契约移除

- [x] 5.1 新增 `/discover`、`/test-draft` 和 `/configure` 路由并接入 Agent edit 与 Secret manage 双重 RBAC
- [x] 5.2 为 discover、test-draft 和 configure 的外部探测阶段增加 actor 与 connection 维度限流，限流命中时不得访问 DeepSeek
- [x] 5.3 增加成功与失败审计，只记录 actor、connection code、脱敏 host、模型、时长、结果和稳定错误码
- [x] 5.4 删除旧 `/revision`、`/credential`、`/test` 管理 HTTP 路由，保留运行时或迁移仍需要的内部领域方法
- [x] 5.5 增加 API 契约测试，覆盖严格 schema、RBAC/CSRF、限流、409 current revision、中文错误、公共响应脱敏和旧路由不可用

## 6. Agent Profile单页配置向导

- [x] 6.1 更新前端 domain schema、API client 和 TanStack mutations，接入 discover、test-draft 与 configure 并删除旧三段式调用
- [x] 6.2 实现 EDITING、DISCOVERED、MAPPED、TESTED、READY 状态机及输入变更后的确定性下游失效
- [x] 6.3 将 Base URL、Credential 来源和 password input 放入同一连接卡片；已有有效 Credential 可选择沿用，缺失时强制输入新 Key
- [x] 6.4 使用模型发现结果渲染主模型及 Opus/Sonnet/Haiku/Subagent 下拉框，并提供“继承主模型”选项
- [x] 6.5 对不在最新列表中的旧模型显示只读旧值和警告，禁止保存新 revision，且不修改历史记录
- [x] 6.6 实现草稿测试与最终保存状态、Provider host/模型/耗时成功摘要，以及鉴权、发现、空模型、模型不可用、SDK、超时、并发和所有权错误
- [x] 6.7 在关闭、导航、输入失效、mutation settle 和保存成功时清空 API Key，确认不进入 Query cache、URL、storage、toast 或持久化表单
- [x] 6.8 删除 Credential Sheet、独立“保存连接版本”和“测试已保存版本”交互，页面只保留统一向导
- [x] 6.9 增加前端交互测试，覆盖首次配置、沿用 Key、主动轮换、模型映射、状态失效、409 恢复、明文清理、权限和窄屏布局

## 7. 集成验证与交付

- [x] 7.1 运行模型连接、Agent Profile、Secret、RBAC、审计、Claude Agent SDK、Publication 和运行时固定连接相关后端测试
- [x] 7.2 运行 Ruff、后端类型/导入检查和 Secret 泄漏扫描，修复所有新增问题
- [x] 7.3 运行前端 lint、typecheck、全量 Vitest 和生产构建
- [x] 7.4 运行 `openspec validate redesign-deepseek-model-connection-setup --strict`
- [x] 7.5 使用同一源码状态重建 `api-server`、`admin-web`、`agent-worker` 和 `dingtalk-stream-ingress`，确认健康与契约一致
- [x] 7.6 在 Web 输入新的 DeepSeek Key，完成 discover、模型映射、test-draft 和 configure，确认连接由 rotation-required 变为 ready
- [x] 7.7 核对数据库只新增受管 Secret 引用、加密版本和一个 ready 连接 revision，日志、审计和浏览器可见状态不含 Key
- [x] 7.8 在 Agent 草稿中选择新连接 revision并完成保存与校验，确认本变更未自动发布 Agent 或切换 Business Application
- [x] 7.9 验证历史 Agent Publication、已固定 Job 和旧连接 revision保持不可变，并记录 api-server/admin-web 成对回滚步骤
