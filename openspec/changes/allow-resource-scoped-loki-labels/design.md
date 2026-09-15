## Context

资源管理端已支持任意合法标签固定条件，MCP 的静态名称白名单则在多层不一致。保留当前唯一 Published Resource Revision、Environment/Base 授权及强制 selector 解析，替换名称名单而不是放开原始 LogQL。

## Goals / Non-Goals

目标：Agent 可发现、枚举和精确过滤资源范围内的任意合法标签；所有请求保持固定条件；参数错误可诊断。

非目标：新增 Loki RBAC 维度、正则/OR/否定过滤、无范围全局枚举、资源自动修改、数据库迁移、真实环境发布或日志数据写入。

## Decisions

1. 新建无外部 I/O 的共享标签契约，使用管理端现有标签名格式 `[A-Za-z_][A-Za-z0-9_]{0,127}` 和有界非空精确值。Schema、入口、领域策略和发现结果共用，消除各层名称名单。结构化精确匹配经统一转义生成 LogQL，不接受模型拼接语法。
2. 已发布资源固定条件由服务端注入，所有四类工具均验证非空范围。任何 Agent 提交固定 key（包括相同值）均明确拒绝；保持现有不可覆盖规则。Agent 省略固定 key 不影响最终条件。固定 key 是数据配置，不特判 customer/workshop。
3. 标签发现和取值枚举只能在固定 selector 内进行；不会请求租户全局 labels/values 作为失败回退。语法合法但没有匹配返回空结果，不伪装为无权限。固定标签的取值枚举也只返回该范围内值。
4. 统一返回明确中文参数错误和稳定码；保留真实授权及 Provider 错误分类。拒绝测试验证不会访问 Provider。
5. 新 Schema 更新 seed 快照；既有发布/Job 不原地修补，须新发布与新 Job。无需更改 Runtime 协议版本或 schema migration。

## Risks / Trade-offs

- 动态 key 可能导致注入 → 使用统一键格式、精确值校验、字符串转义和强制 AND，增加恶意 key/value 测试。
- 发现过程泄露其他客户标签 → mock HTTP 请求验证必含固定范围，不允许空范围或回退全局端点。
- 新旧服务工具 Schema 不同 → 发布新 Agent/Application；既有快照继续按漂移检查失败关闭，不放宽校验。
- 日志计数、截断和 highlights 是独立问题 → 本次不改变其语义。

## Migration Plan

无数据库迁移。代码回归与严格 OpenSpec 校验通过后，由管理员部署兼容服务并重新发布 Agent/Application，使用新 Job 做固定范围内的只读验收。回滚需还原整套对应服务及发布契约，不混用新旧 Schema。

## Open Questions

用户已确认动态标签与固定资源范围边界；真实 Loki 验收需运行环境可用。
