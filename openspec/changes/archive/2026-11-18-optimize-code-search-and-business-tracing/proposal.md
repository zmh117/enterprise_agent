## Why

实际拆批问答多次触发 64 候选文件/10000 枚举限制及不支持的 Grep 参数，最后停留在错误文案而未核验业务分支。现有实现先限枚举再过滤，要求模型手动拆目录；需要宿主自动批次处理，并约束回答的证据强度。

## What Changes

- 保留官方 Read/Glob/Grep 和现有只读 grant；Runtime 在一次 Grep 内分页枚举并分批筛选已核验 UTF-8 源码，保留有界命中文件供原生 Grep 展示。完整性、敏感检测、源码互斥和临时工作区配额不放宽。
- 安全兼容有限文件类型和扩展名花括号写法；范围参数仅有界收紧，不猜测路径/关键词；无法纠正时提供固定字段级提示。
- Skill 增加“文案→错误符号→业务引用→条件/状态→动作顺序→入口”追踪，禁止把文案存在推导成业务规则；连续无效搜索必须调整，不重复空转。
- 同步 Prompt 版本、测试、部署两个 Runtime 和相关调用方；发布新 Skill，并仅更新 assist03 的绑定。
- 原 test2/r52422 任务位于另一环境，无本机访问条件；本机做合成拆批案例和可用真实源码验证，现场复测保留待办。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `task-file-workspace`: 有界自动批次搜索、字段级纠错和完整覆盖标记。
- `platform-operations`: 业务报错追踪与证据分级要求。

## Impact

Runtime 源码枚举/搜索/Hook、Runtime 镜像的 ripgrep、系统 Prompt、版本化 code-business-query Skill、相关回归和部署。本次不改业务数据库结构，不引入 Graphify，不放宽敏感文件保护，不发送钉钉等外部消息。
