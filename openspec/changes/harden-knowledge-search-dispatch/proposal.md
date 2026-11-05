## Why

同一 Job 并行调用知识检索时，会在单执行槽的重排服务中排队并消耗单次预算。现有失败审计不能区分授权、检索、重排排队/计算与 ONES 校验耗时，也不能解释实际截止时间为何早于 360 秒。

## What Changes

- Runtime 在发出知识工具请求前按 Job 串行派发，等待受原 Job 预算和取消控制；检索请求发出时才开始单次最多 360 秒预算。
- 成功与失败审计记录固定阶段计时、有效预算与截止来源；重排记录排队和执行计时，超时无响应时通过安全关联标识定位服务事件。
- 接续请求内已续期的知识 Principal，避免串行等待后使用过期凭证；不延长票据寿命，不改变授权或访问模式。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `builtin-tool-resource`：知识工具预算和不含业务内容的性能审计。
- `execution-delivery`：同 Job 知识工具派发、取消及凭证接续。

## Impact

涉及 Python Runtime、Knowledge MCP、检索应用与重排服务及相应测试。保留在线 ONES 校验、重排模型/候选范围、360 秒上限和 Job 总截止。无需数据库迁移；不包含真实环境部署、容量承诺或此前四小时同步改动的提交。
