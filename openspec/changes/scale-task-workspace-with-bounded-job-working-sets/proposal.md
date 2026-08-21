## Why

当前任务工作区最多只能保存 20 个 ACTIVE 逻辑文件，且每次 Job 会把工作区全部 ACTIVE 文件逐条冻结进 Job File Manifest。直接把上限提高到数百会同步放大数据库快照、Runtime 文件上下文和模型可见目录，既不能满足生产资料量，也会破坏现有有界执行边界。

## What Changes

- 将持久任务工作区与单次 Job 文件工作集分离：工作区默认允许 200 个 ACTIVE 逻辑文件，租户可在受治理范围内调整，平台硬上限固定为 1000。
- Job 创建时不再把全部 ACTIVE 文件复制进 Manifest；只冻结本轮当前附件、引用、精确文件身份和确定性命中的初始项，并附带不超过 50 个不含正文的元数据候选。
- 每个 Job 最多取得 20 个精确 File/Version 内容访问项；Runtime 仍保持现有 40 文件、224 MiB 沙盒硬限制，未选中的工作区文件不得物化到沙盒。
- 新增受治理的工作区文件发现能力：使用游标分页以及名称、格式、来源时间和状态过滤返回有界元数据与精确 `file_id + version_id`，不得返回正文、对象位置或凭据。
- Agent 从发现结果选择文件时，File Service 实时复核 Job、用户、租户、会话、Publication、工作区和版本状态，并把精确选择写入 Job 级追加式工作集事实；达到 20 个后失败关闭。
- 工作区配额由平台/租户治理策略决定，不写入 Business Application Publication；Job 记录当时生效的配额策略版本、目录观察时间和工作集选择事实以便审计。
- 采用分阶段兼容上线：先发布有界发现/选择工具与兼容 Agent/Application Publication，再把租户有效上限从 20 提升到默认 200；不升级或改写 Runtime 1.2/1.3 协议。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `task-file-workspace`: 拆分持久工作区容量、元数据候选和 Job 内容工作集，增加租户级有效配额和分页发现要求；既有到期及保留文件召回边界保持不变。
- `execution-delivery`: Job File Manifest 改为有界初始清单，并增加 Job 执行期间追加式、精确且可审计的文件工作集事实；保持既有 Runtime 协议版本。
- `builtin-tool-resource`: 增加封闭 Schema 的工作区文件发现/选择能力，并要求所有调用继续使用 File MCP Principal 与实时授权复核。
- `business-application`: 新 Publication 在启用大工作区能力时必须冻结兼容的 File MCP Tool 子集；配额数值本身不得进入 Application Publication。
- `platform-operations`: 平台运行配置增加默认值 200、硬上限 1000 和租户覆盖的治理、审计与上线门禁。

## Impact

- 数据与迁移：复用平台运行配置保存租户工作区配额，新增 Job 文件工作集追加事实；为 ACTIVE 文件目录的分页/过滤增加组合索引，不回填或改写历史 Manifest。
- File Service：配额解析、Manifest 生成、目录查询、File MCP 授权、归档/召回和审计路径。
- Control Plane：Job 文件上下文解析和兼容 Publication 校验；初始候选与内容工作集均保持硬上限。
- Agent/Runtime：新增固定 File MCP 工具定义和 Agent 提示；保持 Runtime 请求协议与沙盒限制不变。
- 管理与运维：租户配额配置/诊断、兼容性预检、分阶段启用以及 200/1000 文件和并发 Job 压测。
