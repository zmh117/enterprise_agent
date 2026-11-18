# 本机验证记录

2026-11-10 20:33 +08:00。与代码业务回复规则（提交 `ffb58fe5`）联合验证、构建和更新；没有调用真实模型或运行真实业务诊断。

## 实现与测试

- 319 项联合回归通过，覆盖源码版本/内容与路径边界、笔记权限、受限内容跳过、预算、并发搜索、准备线程取消、清理、工具审计、轮次计数、文件 MCP、Runtime 及业务回复投影。
- 非 root、无网络、只读容器中 13 项真实 SVN CLI 隔离仓库测试通过，包含 GB18030 中文文件核验、候选仅含受管文件和缓存清理。
- 实际 Claude Agent SDK 0.2.178 / CLI 2.1.318 加容器内合成 Provider 验证通过：目录多文件搜索与原行号还原、中文转码、文件名模式与零命中、Write/Read 笔记、禁止 outputs 写入、搜索缓存清理；6 次工具调用保留审计，4 个纯读取轮次免计。没有真实模型、凭据或业务源码挂载。
- Ruff 与 9 个变更应用模块 Mypy 通过；OpenSpec change、execution-delivery、task-file-workspace、builtin-tool-resource strict 校验通过；diff whitespace 检查通过。

## 部署

- 更新前活动 Job 与未静止 invocation 均为 0；两个 Runtime draining=true、busy=false 后停止消费者和 API，再重建并恢复服务。
- API、两个 Agent Worker、Job Dispatcher、knowledge-mcp、Runtime a/b 已更新。API、Dispatcher、knowledge-mcp、Runtime health 正常，两个 Agent Worker 已运行。
- API 被动检查池 READY，两节点身份 verified、Prompt v16 MATCH、draining=false、busy=false，SDK 0.2.178、CLI 2.1.318；节点确认代码派生工具为 Read/Glob/Grep/Write，Write 归 code-source 权限策略。
- 两节点各核对 11 个源码文件 SHA-256 与工作区相同；API 和两个 Worker 各核对 6 个相关文件，Dispatcher 3 个，knowledge-mcp 2 个，均相同。
- Runtime a 镜像：`sha256:7c8dd4d34ed77153bf19654fdb08a2e30d8f814c9f6b4eb2aa4874a3aeee0df8`。
- Runtime b 镜像：`sha256:beb1acdfbfaa4de0b8ecc47597d452fd20ee7449a9f0694de3d0362a2a1610f3`。
- 更新后活动 Job 和未静止 invocation 仍为 0，没有重跑历史任务。

## 证据边界

上述为合成输入功能测试和本机服务检查，不宣称真实模型回答质量或耗时提升。20:33 时 assist03 应用第 69 版仍固定引用 Agent 第 53 版，旧发布 Skill 不会被磁盘更新覆盖；后续发布核对见下节。

## 发布核对与入口进程补更

2026-11-10 20:55 +08:00。用户已授权发布并仅更新 assist03。本次检查时，第 54、55 版 Agent 和第 70、71 版应用已通过管理操作发布；assist03 在 20:49:21 已激活应用第 71 版、Agent 第 55 版，因此不重复创建发布。

- 当前应用 Publication：`business_app_publication_7c4c6589a3ef474ca79f4b82cb929952`；Agent Publication：`agent_publication_f10bcf1fd5944a39a0e14650e8318396`；local Deployment 修订 45、active=true。
- 冻结 Skill SHA-256 为 `f27c0e09c64a9b12460aa14033f29564f843e74a276a6020ec01ccf21fcc248f`，与当前 Skill 内容及重新计算的摘要完全相同，包含 work/notes 和 glob 批量搜索规则。
- 其他现存应用 mes-code-extractor 仍为原 local Deployment 修订 7、应用第 8 版；本次没有修改其他应用或任何历史 Publication。
- 20:45 后审计中有 5 次钉钉消息因“所选 Agent Runtime 当前未就绪”被拒绝。复现发现 Channel Dispatcher 仍为 Prompt v15，而 Runtime 为 v16，成员身份、数据库和主密钥均就绪，但 Prompt MISMATCH 导致池 UNAVAILABLE。Webhook Worker 也仍为 v15。此前仅核对 API 与执行 Worker，遗漏了创建任务的入口进程。
- 已构建并重建 channel-dispatch-worker 与 webhook-worker，保留其他容器、数据和历史消息。镜像分别为 `sha256:7170989bda2aca4e92ea20a85a17b6a56b7a9d961269052c862fc7e60a333bc8`、`sha256:7e509a87f1e3c01b60e13aa75ad950528671f9d0d0b6c3fb8f2755304ad4941f`。
- 两入口容器 healthy；使用各服务正常配置加载流程，从 API、Channel Dispatcher、Webhook Worker 的创建任务就绪守卫检查，两 Runtime 均为身份 verified、Prompt v16 MATCH、池 READY。检查没有调用模型或 MCP。
- Runtime HTTP、就绪检查与应用路由相关 90 项回归通过。运维文档补全协调升级服务清单，明确 heartbeat healthy 不能代替 Prompt 一致性检查。
- 未重放已拒绝消息，未执行真实模型问答；修复后的真实钉钉新问题仍需另行验证。
