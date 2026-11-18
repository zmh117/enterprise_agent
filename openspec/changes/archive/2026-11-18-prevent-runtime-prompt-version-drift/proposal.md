## Why

生产报错显示冻结请求期待 Prompt v8、Runtime 观测为 v10。目前健康探针只核对协议和构建身份，没有核对 Prompt；新调用也直到工具观测事件才暴露差异。默认 local-dev 构建标识使局部升级更难提前发现。

## What Changes

- Runtime 的版本与就绪接口声明实际 Prompt 模板版本，平台被动探针核对与期望版本一致。
- 池只将新执行发给匹配冻结请求版本的节点；无匹配节点沿用有界准入等待。
- Runtime 在新执行取得槽位和开始模型/MCP 工作前拒绝不匹配请求，返回固定错误码和安全提示。
- 恢复已有执行与终态重放保留原事件，不因当前代码模板变化改写历史。
- 补充生产所有副本版本核对、统一发布及冻结请求排查说明；不访问生产凭据或原文、不重启本地服务。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `execution-delivery`：Prompt 版本一致性前移到新执行准入和被动就绪检查，严格事件校验保持。

## Impact

影响 Runtime 版本/就绪元数据、Worker 池选路、Runtime 新调用准入、传输错误映射、回归和运维说明。不改变 Prompt 内容/版本，不新增数据库迁移、兼容版本协商或自动重放业务任务。
