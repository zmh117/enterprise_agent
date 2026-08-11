## Context

平台长期运行一个 Worker 与两个独立 Agent Runtime。Worker 拥有业务事务；Runtime 只执行一次模型 attempt。工具协议已经统一为固定标准 `tool-mcp`。

## Goals / Non-Goals

**Goals:**

- 长期支持 `python-v1` 与 `typescript-v1`；
- 以严格协议隔离模型 SDK；
- 固定 Runtime、模型连接和 MCP Tool 发布事实；
- 归一化事件、取消、终态、错误和敏感内容边界。

**Non-Goals:**

- 不让 Runtime 消费 RabbitMQ 或写业务表；
- 不提供任意 MCP Server、URL、Shell、脚本或写工具；
- 不让 Runtime transport failure 自动切换另一 Runtime；
- 不新增 MCP 专用 Token、签名、RBAC 或资源映射。

## Decisions

### 1. Worker 与 Runtime 分离

Worker claim Job、决定 retry、完成结果事务并创建 Delivery；Runtime 验证单次 Runtime Grant，执行 SDK，输出单调 sequence 和唯一终态。

### 2. Runtime kind 是发布事实

Agent Definition 创建时确定 Runtime kind。Agent Publication 和 Job 固定该事实；重试沿用原 Runtime。

### 3. 工具统一走标准 MCP

两个 Runtime 只注册固定 `tool-mcp` 中 Job 允许的精确工具。`allowedTools` 与 `canUseTool` 双重失败关闭；危险 SDK 工具进入固定 denylist。

`tool-mcp` 根据 Job 快照和当前授权复核调用，并从已发布资源中唯一解析目标。MCP transport 本身不携带业务授权 Token；Runtime Grant 也不传给 MCP。

### 4. Secret 隔离

模型 Key 由 Runtime 按固定模型连接 revision/config hash 读取；Master Key 为只读文件。Secret、完整 Prompt、private thinking 和原始 Provider/MCP payload 不进入 RabbitMQ、日志、Runtime ledger 或响应。

### 5. Probe 与正式执行复用安全边界

模型 probe 禁止 Tool，固定单轮/短超时，只返回脱敏 host、model、耗时和 Runtime/SDK 版本。

## Risks / Trade-offs

- 跨服务延迟与故障点：私有网络、严格超时、幂等 invocation、终态 ledger。
- 跨语言协议漂移：单一 JSON Schema、golden fixture、consumer/provider contract。
- 双 Runtime 行为差异：等价用例和真实 Runtime provenance，不做隐式 fallback。

## Migration Plan

实现已由双 Runtime 规格完成；当前活动变更只保留协议事实。工具迁移和旧平台退役由 `retire-legacy-api-platform-for-mcp` 负责，不能再恢复过渡适配器。
