## Why

当前 Agent 面对约 200MiB、20 个异构 LOG 时，只能反复使用 `Grep`、`Read` 和按需物化探索原文，容易在 Job 固定墙钟预算内耗尽时间，且模型重试式搜索不能证明扫描覆盖率。需要一个受沙盒和 Job 冻结权限约束的单次流式证据扫描能力，让程序完成全量字节遍历与有界证据选择，Agent 只负责基于证据诊断和生成报告。

## What Changes

- 新增 Runtime 派生的只读日志证据扫描工具 `mcp__file_service__scan_log_evidence`；它只处理当前 Job 已物化到 `inputs/` 的精确 UTF-8 LOG，不访问对象存储、网络或沙盒外路径。
- 扫描器以有界内存单次遍历最多40个输入和当前224MiB Sandbox预算内的全部日志，返回精确文件/字节/行覆盖统计，并生成一个受统一Sandbox预算约束的临时证据包供Agent读取。
- 扫描器不要求项目日志格式、用户行为字段或解析Profile；它使用代码发布且版本固定的通用标志、保守多行块规则和调用方提供的有界字面关键词选择证据，无法可靠解析的时间、级别或语义必须明确标记为未知。
- 证据包允许在当前Job授权边界内保留排障所需的用户名、业务字段、堆栈和原文片段；持久化Tool事件、审计、错误和队列消息仍只保存有界元数据，不复制原始日志、完整证据包或凭据。
- 相同输入身份和扫描参数在同一Sandbox中幂等复用相同证据包；取消、超时、完整性失败或容量不足时清理未完成文件并释放预留，不提交部分证据为成功结果。
- Runtime提示与结果合同要求最终报告区分精确扫描事实、启发式候选和模型推断，并在证据选择达到上限时声明限制，不把“扫描全部字节”表述成“语义理解全部日志”。
- 增加异构格式、安全路径、容量、取消、Tool合同、审计内容和约200MiB合成日志批次的回归及Compose验证。
- 本变更不提高15MiB单文件、40个输入、64个文件或224MiB Sandbox上限，不支持非UTF-8自动转换，不引入任意正则/脚本、向量数据库、持久化分片编排、断点续跑或Docling日志处理。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `task-file-workspace`: 为当前Job已授权并已物化的LOG增加受统一Sandbox预算约束的流式证据扫描与临时证据包规则。
- `execution-delivery`: 将日志证据扫描器纳入Runtime派生Tool合同、执行预算、安全事件持久化和证据型最终报告规则。

## Impact

- Python Runtime 的Job Sandbox、Runtime派生File Tool装配、Tool schema/hash、权限回调、取消和Tool事件规范化。
- Agent上下文与提示约束、Runtime协议中有界扫描结果元数据，以及调试/审计投影。
- File MCP相关合同测试、Python Runtime单元/集成测试和约200MiB异构日志批次验证。
- 不涉及数据库migration、File Service对象模型、MinIO凭据边界、RabbitMQ消息正文、Business Application/Agent Publication schema或全局执行超时默认值。
