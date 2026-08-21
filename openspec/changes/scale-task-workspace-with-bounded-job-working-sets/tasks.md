## 1. Schema 与受治理配额配置

- [ ] 1.1 使用下一可用migration增加`task_workspace.catalog_revision`、Job File Snapshot配额/目录审计字段、`agent_job_file_working_set_item`追加事实表、唯一约束和ACTIVE目录分页索引，并同时更新SQLite/PostgreSQL schema contract、migration ledger与迁移测试。
- [ ] 1.2 在Platform Runtime Config增加仅允许代码声明定义使用的`tenant` scope、严格tenant身份校验和确定优先级，补API、repository、effective snapshot与配置审计测试。
- [ ] 1.3 注册非敏感整数`FILE_WORKSPACE_ACTIVE_FILE_LIMIT`，默认200、仅适用File Service并在定义校验和消费端双重实施`1..1000`硬范围；现有tenant迁移后先保持有效20直到兼容预检通过。
- [ ] 1.4 扩展管理端Runtime Config表单/诊断以安全选择tenant scope、显示有效值/来源/revision和当前ACTIVE用量，不允许普通请求或Agent声明tenant配置上下文。

## 2. 工作区配额与目录revision

- [ ] 2.1 重构`WorkspaceQuotaService`从认证tenant的有效配置快照读取文件上限并返回值、来源、revision，删除错误文案中的硬编码20但保留代码硬上限1000与100MiB临时容量。
- [ ] 2.2 在所有新增逻辑文件入口以事务安全方式执行ACTIVE数量配额，验证并发导入/提交不会突破有效上限；既有逻辑文件新版本不重复计数。
- [ ] 2.3 实现降低配额后的超限语义：既有文件可读、既有逻辑文件可在容量内创建新版本、新逻辑文件失败关闭；`task_workspace_get`返回当前有效限制和配置revision。
- [ ] 2.4 让ACTIVE成员、逻辑名和`selected_version_id`变化在同一事务单调递增`catalog_revision`，覆盖导入、提交、冲突解决、生命周期清理与并发更新测试。

## 3. 有界初始Manifest

- [ ] 3.1 重构Manifest生成，移除默认复制全部ACTIVE文件的查询路径，只冻结去重后最多20个确定性内容依赖和最多50个`READ_METADATA`候选。
- [ ] 3.2 为超过20个确定性内容依赖及超过50个候选实现固定安全说明、`truncated`/缩小范围语义和无Job路径；已导入文件必须继续保留在工作区且不得静默丢弃。
- [ ] 3.3 在Job File Snapshot记录有效工作区配额、配置revision/source、目录revision、候选上限和内容工作集上限，但保持Manifest schema v4/hash及历史v1-v4读取完全兼容。
- [ ] 3.4 增加20、200和1000文件合成测试，证明Snapshot/Runtime Manifest只包含本轮有界项，当前附件、引用、完整文件名、时间候选、Docling处理中/可用表示和既有时间字段语义均正确。

## 4. 工作区目录发现Tool

- [ ] 4.1 在File MCP代码Manifest新增`task_workspace_search_files`固定identifier和封闭schema：cursor、1..50 limit、完整名/名称前缀、代码注册格式、UTC来源时间和可读状态过滤；更新schema hash边界测试。
- [ ] 4.2 实现ACTIVE工作区目录的确定性keyset分页、过滤、`observed_at`、`catalog_revision`与不透明cursor；cursor绑定workspace、过滤摘要、revision和最后排序键，变化时返回`workspace_catalog_changed`。
- [ ] 4.3 保持`task_workspace_list_files`只列当前Job Snapshot；为新搜索Tool增加Principal、RUNNING Job、tenant、Session、Publication、Tool Snapshot/schema hash、角色与会话归属复核。
- [ ] 4.4 补目录搜索安全测试：跨workspace ID、身份字段、Bucket/对象键/URL、limit>50、非法时间/格式/状态、并发revision变化均在内容或对象访问前失败关闭。
- [ ] 4.5 将搜索调用接入统一MCP Operation Audit，只记录有界过滤摘要、目录revision、返回数量、耗时和安全错误码，不记录正文、Principal、对象位置或凭据。

## 5. 追加式Job内容工作集

- [ ] 5.1 实现`agent_job_file_working_set_item`repository和领域服务：精确File/Version、可选Representation/hash、选择来源、目录revision、序号和时间只追加，重复选择按`job_id + file_id + version_id`幂等。
- [ ] 5.2 扩展`file_prepare_materialization`授权：初始Manifest项沿用旧路径；Manifest外项只有在Job冻结新搜索Tool及现有prepare Tool时才可在实时复核后原子晋升。
- [ ] 5.3 以初始内容项和追加项去重实施每Job20项硬上限；第21项返回`job_file_working_set_limit_exceeded`且不创建事实、transfer或Sandbox文件。
- [ ] 5.4 动态选择文本时冻结精确Version，选择文档时冻结当时精确AVAILABLE/PARTIAL Markdown Representation身份、大小和hash；当前Version或目录revision变化时要求重新搜索，不猜测最新版本。
- [ ] 5.5 确保追加选择只授予受治理读取，不自动授予EDIT、COMMIT或DELIVER；所有物化继续实时复核当前授权并写统一审计。
- [ ] 5.6 增加并发幂等、跨workspace/tenant/Session、旧Job无新Tool、权限撤销、第21项、Representation替换和Runtime断线恢复回归，证明Manifest/hash/request digest未被改写。

## 6. Agent/Application Publication兼容门禁

- [ ] 6.1 将新搜索Tool加入兼容Agent Tool Envelope和Agent文件提示，指导Agent按“搜索元数据→选择精确File/Version→准备物化”工作，不声明workspace或读取未选中文件。
- [ ] 6.2 更新Business Application草稿/发布校验：面向大工作区的新Publication必须显式冻结新搜索Tool及既有必要File MCP Tool，配额值不得写入Publication。
- [ ] 6.3 保持历史Publication在不超过20个ACTIVE文件时的Manifest-only行为；历史Publication遇到超过20个ACTIVE文件时在Job创建前返回`file_workspace_publication_upgrade_required`，不得生成不完整Manifest或动态晋升。
- [ ] 6.4 实现tenant配额提升预检，列出不兼容的启用Agent/Application Publication安全身份并阻止从20或以下提升到20以上；不得自动修改或重发Publication。
- [ ] 6.5 补管理前后端联动、Publication不可变、Tool schema drift、旧Job/旧Publication和tenant配额变化回归测试。

## 7. Runtime、性能与上线验证

- [ ] 7.1 保持Runtime 1.2/1.3合同和Sandbox 40文件/224MiB限制不变，增加合同测试证明动态选择通过既有File MCP transfer进入Sandbox且不需要新Runtime字段。
- [ ] 7.2 建立200/1000 ACTIVE文件、50候选、20内容项、多并发Job和Docling并发处理压测，记录Snapshot行数、Manifest字节、Job创建P50/P95、搜索P50/P95、数据库查询计划及上限拒绝。
- [ ] 7.3 运行File Workspace、Platform Config、Business Application、File MCP、Python Runtime相关测试和完整后端回归，并执行前端静态检查、OpenSpec strict validation、`docker compose config --quiet`与`git diff --check`。
- [ ] 7.4 先发布兼容Agent/Application Publication并保持tenant有效上限20，保存只读预检证据；通过后把目标tenant提升到200并记录配置审计。
- [ ] 7.5 完成真实Runtime→File MCP搜索→精确选择→Docling Markdown物化→Agent读取→回复或Delivery全链E2E，证明未选中的工作区文件没有进入Sandbox；容器健康不得作为替代证据。
- [ ] 7.6 编写回滚与运行手册：先把tenant上限降回20、停止新兼容Publication流量、保留超限工作区只读及历史追加事实，禁止删除或改写已完成Job。
