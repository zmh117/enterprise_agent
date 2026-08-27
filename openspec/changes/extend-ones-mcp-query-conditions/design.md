## Context

当前 `ones_query_work_items` 使用代码固定的 GraphQL 文档，并把有限业务参数转换为 `filterGroup`。已有工具可实时发现项目、迭代、事项类型和人员，但不能按中文名称解析精确状态或自定义选项，也不能表达 ONES 的 `_<字段 UUID>_in` 条件。新增的 `查用户.md` 证明存在固定 REST `POST /project/api/project/team/{team_uuid}/users`，请求体只含用户 UUID 列表，但原始响应还包含邮箱、手机号、部门等本次不需要的个人字段。

`ones_mock/ones/查询条件字典.yaml` 是个人身份在一个 ONES Team 下于特定日期采集和人工整理的约 97 KB 快照。它同时包含状态、项目、迭代、事项类型、人员与选项字段。该目录被 Git 忽略，现有架构禁止生产、Mock 和测试在运行时直接读取。直接把全量 YAML 暴露给 Agent 会造成提示词膨胀、人员信息扩散和跨 Team UUID 误用。

## Goals / Non-Goals

**Goals:**

- 让 Agent 能把中文状态或自定义选项解析为当前受管快照中的候选 UUID，并处理同名歧义。
- 新增 `ones_query_work_items_with_custom_options`，仅接受字典允许的自定义选项字段与选项 UUID，继续使用固定 GraphQL 文档，并保持既有 `ones_query_work_items` 契约与 schema hash 不变。
- 提供按明确 UUID 批量查询用户的固定只读 REST Tool，只投影 UUID 与姓名。
- 让字典资源按 Team、版本、采集时间和内容摘要可校验，且不包含人员、项目、迭代、凭据或原始响应。

**Non-Goals:**

- 不实现任意 GraphQL、REST、筛选键或自由 JSON 执行器。
- 不支持自定义文本、日期、数值、用户、多级联动等尚无真实请求证据的字段类型；本次仅支持单选/多选 UUID 条件。
- 不把个人抓取中的人员、项目或迭代列表作为授权、实时可见性或全局租户事实。
- 不定义“响应时间”“完成”等统计口径，也不新增 Agent Skill；这些按用户要求留到后续独立变更。
- 不自动修改既有 Agent/Application Publication 或已冻结 Job。

## Decisions

### 1. 生成最小、Team 受限的运行字典，而不是读取原始抓取目录

新增确定性同步脚本，从被忽略的 YAML 中只提取 `status_in` 与 `all_option_fields`，并把内联字段中文名转换为显式结构。生成的运行资源包含 schema version、来源 Team、采集日期和源摘要；加载时执行结构、大小、UUID、唯一性与内容摘要校验。运行 Tool 必须先确认 `principal.team_id` 与资源 Team 一致，否则失败关闭。

不会复制 `assign_in`、`project_in`、`sprint_in`、`issueType_in`、原始请求/响应或任何 Header。项目、迭代、事项类型和人员分别继续调用实时 MCP 工具。这比运行时挂载个人 Mock 目录更可部署，也比把全量 YAML 注入 Skill 更节省上下文并减少数据暴露。

### 2. 用固定本地资源 Tool 做按需名称解析

新增 `ones_resolve_query_conditions`，输入条件类型、关键词、可选字段关键词和 limit，输出有界候选。状态候选返回状态 UUID、名称和类别；自定义选项候选只返回字段 UUID/名称与选项 UUID/名称，Provider 筛选键仍留在服务端。精确名称优先，其次做规范化后的包含匹配；同名不自动择一。

该 Tool 仍经过 Principal JWT、Publication、Job snapshot 和 Team 校验，但不发起 Provider 请求、不触发 Credential refresh，也不把整份字典写入审计。审计只记录条件类型、规范化关键词长度、返回数量、字典版本与匹配结果摘要。

备选方案是把字典直接拼入 Agent 上下文；因每次 Job 都会增加大段静态上下文且难以执行 Team 强校验，予以拒绝。

### 3. 自定义筛选使用结构化业务参数并由字典强校验

新增 `ones_query_work_items_with_custom_options`，保留 `ones_query_work_items` 的标准筛选并增加 `custom_option_filters`；每项只包含 `field_uuid` 和唯一、有界的 `option_uuids`。服务在解析 Principal 后验证字段和每个选项均存在于同一受管字典，再确定性构造 `_<field_uuid>_in`；Agent 不能提交原始 Provider filter key。字段数量、每字段选项数和总体请求大小均设上限，重复字段、空选项、未知字段或跨字段选项全部拒绝。

不直接扩展既有 Tool，是因为平台把输入 schema hash 冻结到 Publication 与 Job snapshot；原地改变 schema 会让历史快照与当前 Manifest 发生漂移。新 Tool 复用相同固定 GraphQL operation，但拥有独立治理身份和显式新 Publication 边界。

GraphQL 文档仍位于 `provider/graphql/documents/`，没有动态查询文本；仅变量中的固定 `filterGroup` 增加已校验条件。

### 4. “查用户”复用已验证的固定 REST Operation

新增 `ones_get_users_by_uuids`，输入唯一、有界的 `user_uuids`。实现复用现有 Team users 固定 POST operation，并把返回映射转换为稳定列表。输出只含 UUID 与姓名；邮箱、电话、部门、头像、公司、MFA、邀请人等字段即使 Provider 返回也不投影、不审计。

现有 `ones_search_team_users` 继续负责按关键词发现人员；新 Tool 用于已有 UUID 的批量反查，不合并两个不同语义。

## Risks / Trade-offs

- [静态选项在 ONES 中发生漂移] → 资源带采集日期和摘要；未知值失败关闭，更新必须重新同步、测试、发布镜像和 Agent/Application Publication。
- [同名状态或选项导致误筛选] → 返回全部候选并要求 Agent 结合字段/上下文确认，不按首项自动选择。
- [Team 内字段值仍可能超出某用户项目可见范围] → 字典只帮助构造条件，真实工作项查询仍由当前个人 Token 和 ONES 权限执行；不返回项目/人员静态列表。
- [自定义字段类型不兼容 `_in`] → 生成器仅接受源字典中标为单选/多选的字段；其他字段类型不进入运行资源。
- [新增 Tool 不出现在旧 Job] → 保持不可变 Publication/Job snapshot 语义，通过显式重新发布升级。

## Migration Plan

1. 生成并审查最小字典资源，运行安全扫描确认不含人员段、Header、邮箱和手机号。
2. 发布共享 Tool 契约、ONES MCP 实现与合成 Mock，并完成定向测试；确认既有 `ones_query_work_items` schema hash 未变化。
3. 重建 `api-server` 与 `ones-mcp` 镜像，验证 Tool 和字典资源进入对应镜像。
4. 创建新的 Agent Publication，选择新增 ONES Tools；再显式发布并激活需要使用它的 Business Application。
5. 回滚时切回旧 Publication/Deployment；旧 Job 不受资源更新影响。

## Open Questions

无。统计口径明确留在后续用户需求中，不阻塞本次基础查询能力。
