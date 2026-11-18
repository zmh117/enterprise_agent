## Why

当前 `ones_query_work_items` 按规范和代码在累计1000条时停止，用户提供的记录显示上游报告4715条但只收集1000条。用户现要求将该工具上限提高到10000；这是明确的条数策略调整，不是放宽分页完整性校验。

## What Changes

- 仅将 `ones_query_work_items` 的累计收集、输出数组及计数上限提高到10000，最多200次分页请求，支持上游每页只返回50条。
- 单页仍最多200；保留90秒、8MiB、HTTP/Job/Sandbox预算、游标稳定性、授权和失败关闭。
- 其他八个GraphQL列表上限不变，包括仍为1000的 `ones_work_item_search` 与 `ones_query_work_items_with_custom_options`。不修改REST、详情、写工具或公开输入。
- 同步工具描述、回归和本地验证记录；不连接真实ONES、不修改配置/发布快照、不自动重跑历史Job。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `governed-api-capability`：调整标准工作项查询的有界收集上限和分页请求预算，明确与其余工具的边界。

## Impact

- 共享ONES工具上限/输出schema、GraphQL收集服务的代码固定预算选择、服务说明和测试。
- 输入schema与hash不变；输出校验变化要求ONES与Runtime等共享合同消费者使用相同代码版本。
- 实现及本地合成验证不代表用户其他环境已部署或真实ONES已验收。
