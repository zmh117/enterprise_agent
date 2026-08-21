## 1. Schema、配置与审计事实

- [x] 1.1 使用下一可用forward migration增加不可变工作区目录revision及时间化成员、Manifest v5头部、`agent_job_file_working_set_item`、事务配额预留事实和分页/清理索引；同步更新SQLite/PostgreSQL schema contract、migration ledger与迁移测试。
- [x] 1.2 为Platform Runtime Config增加只有代码声明为tenant-compatible的定义可用的`tenant` scope，实施认证tenant身份校验、确定优先级、乐观revision和配置审计，补API、repository与effective snapshot测试。
- [x] 1.3 注册`FILE_WORKSPACE_ACTIVE_FILE_LIMIT`（默认200、代码硬上限1000）和`FILE_WORKSPACE_BILLABLE_BYTES_LIMIT`（默认2GiB、代码硬上限10GiB），在定义校验、管理API和File Service消费端重复夹紧硬上限。
- [x] 1.4 扩展Job File Snapshot/审计字段，记录创建时观察到的两个有效配额、配置revision/source、目录revision、Manifest版本、40项输入与Sandbox限制版本；不得记录目录正文、对象位置或凭据。
- [x] 1.5 扩展管理端Runtime Config表单与诊断，安全选择tenant scope并显示两个有效值、来源、revision、实际用量和预留量；普通业务请求和Agent不得声明tenant配置上下文。

## 2. 工作区数量、字节配额与事务预留

- [x] 2.1 重构`WorkspaceQuotaService`，从认证tenant的同一有效配置快照读取文件数和计费字节上限，返回值、来源和revision；移除20/100MiB硬编码，同时保留1000/10GiB代码硬上限。
- [x] 2.2 明确定义并实现工作区计费用量：工作版本、开放冲突、未终结staging、派生表示与处理资产按稳定不可变对象身份去重计费；原件、表示和临时事实不得重复或遗漏计费。
- [x] 2.3 为导入、处理、提交、新版本、冲突和派生内容实现事务文件数/预计新增字节预留；成功转为实际用量，失败或过期可幂等释放，禁止先写对象再在终点发现超限。
- [x] 2.4 覆盖并发创建、同一逻辑文件新版本、重复对象、处理重试和冲突提交测试，证明ACTIVE逻辑文件数与计费字节均不会在竞争下突破有效上限。
- [x] 2.5 实现配额降低语义：超限工作区已有内容可按当前授权读取，任何继续增加对应超限维度的逻辑文件、版本、staging或派生处理失败关闭；诊断返回当前用量、预留、限制和revision。

## 3. 不可变目录revision与Manifest v5

- [x] 3.1 在ACTIVE成员、逻辑名或`selected_version_id`变化事务中创建下一不可变目录revision，并关闭/新增受影响成员的有效区间；覆盖导入、提交、冲突解决、生命周期清理和并发更新。
- [x] 3.2 实现按冻结revision查询时间化目录成员的确定性keyset分页，保证同一Job在当前工作区变化后仍得到稳定旧分页，新Job冻结新revision；不得为每个Job复制200至1000个目录条目。
- [x] 3.3 增加目录revision引用保留与安全压缩/清理规则：任何非终态或历史Job仍可审计、重放的revision不得删除或改变成员语义。
- [x] 3.4 发布Manifest v5，只冻结`workspace_catalog_revision_id`、当前附件、明确引用及预选工作集；移除全ACTIVE列表和元数据候选复制，条目去重后受40项输入上限。
- [ ] 3.5 在Job与dispatch outbox写入前，对全部计划自动物化输入按唯一File/Version数量和实际文本/Markdown大小执行完整预检；超过40项或224MiB时不创建Job、不投递outbox、不截断为子集。
- [x] 3.6 对Office、PDF和图片只冻结精确原件身份与可读Markdown Representation，预检和Sandbox只计算实际进入Sandbox的Markdown，每个原始File/Version计一个输入，原始二进制不得进入Runtime。
- [x] 3.7 增加Manifest v1-v4历史读取、v5 hash/不可变性及Runtime 1.2/1.3投影合同测试，证明目录revision不要求Runtime协议升级且历史Job不被回填或扩权。

## 4. 冻结目录发现Tool

- [x] 4.1 在File MCP代码Manifest新增`task_workspace_search_files`固定identifier与封闭schema：cursor、1..50 limit、完整名/名称前缀、代码注册格式、UTC来源时间和可读状态过滤；更新schema hash边界测试。
- [x] 4.2 Tool服务端只从File MCP Principal和Job Manifest解析Job、主体、tenant、Session、Publication、workspace及`workspace_catalog_revision_id`；拒绝模型声明身份、revision、Bucket、对象键、URL或凭据。
- [x] 4.3 返回不含正文的安全元数据、精确File/Version、`observed_at`、冻结revision和不透明cursor；cursor绑定workspace、过滤摘要、revision及最后排序键，每页默认20、最多50。
- [x] 4.4 保持`task_workspace_list_files`只列当前Job初始Snapshot；新搜索结果只构成可选择身份，不写入Manifest、不自动授予MATERIALIZE/EDIT/COMMIT/DELIVER，也不占40项直到精确选择。
- [x] 4.5 增加稳定分页、当前目录变化、跨workspace/tenant/Session、非法limit/过滤、历史版本内容已清理和权限撤销测试；冻结V3仍可访问时精确选择V3，不得静默替换为当前V4。
- [x] 4.6 接入统一MCP Operation Audit，只记录有界过滤摘要、冻结目录revision、返回数量、耗时和安全错误码，不记录正文、Principal JWT、对象位置或凭据。

## 5. 追加式Job输入工作集

- [x] 5.1 实现`agent_job_file_working_set_item` repository与领域服务，保存Job/Snapshot、workspace、冻结目录revision、精确File/Version、可选Representation/hash、来源、序号和时间；`job_id + file_id + version_id`唯一且只追加。
- [x] 5.2 扩展`file_prepare_materialization`：初始Manifest项沿用旧路径；Manifest外项只有在Job冻结兼容搜索与prepare Tool后，经过RUNNING Job、Principal、角色、会话、冻结revision归属和当前内容授权复核才可原子晋升。
- [x] 5.3 以初始项与追加项去重实施每Job 40个不同File/Version硬上限；重复选择复用既有事实与sandbox handle，第41项在创建事实、transfer或文件前返回`job_file_working_set_limit_exceeded`。
- [x] 5.4 对文档冻结选择时精确AVAILABLE/PARTIAL Markdown Representation身份、大小与hash；内容失效、representation替换或授权撤销时失败关闭，不重新解析当前最新版本。
- [x] 5.5 证明追加选择不改写初始Manifest/hash、Runtime request digest或Runtime 1.2/1.3字段，不自动授予EDIT、COMMIT或DELIVER；重试与Runtime断线恢复复用相同精确事实。
- [x] 5.6 增加并发幂等、跨边界、旧Job无新Tool、第41项、Representation替换、权限撤销和恢复回归，并在允许/拒绝路径写统一安全审计。

## 6. Runtime统一Sandbox预算

- [x] 6.1 将Python Runtime和`JobSandbox`默认/硬限制改为64个常规文件与224MiB：`inputs`最多40、`work/outputs`合计最多16、内部`tmp`与安全余量8；保持15MiB单文件限制。
- [x] 6.2 在`JobSandbox`实现并发安全的统一预算与预留API：自动输入整批预留、按需输入预留、工作/输出预留和内部临时预留；全部分区共享真实224MiB使用量。
- [x] 6.3 让Runtime在首次模型请求前对全部自动物化输入整批预留并再次校验；任一项超限、下载失败或完整性失败均完整终止Job、清理部分文件并释放全部预留，不允许部分输入继续执行。
- [x] 6.4 重构`FileTransferCoordinator._materialize`，强制持有当前Sandbox输入预留后才可创建目标文件或下载首字节；禁止File MCP、测试替身或新增bridge路径直接`open("xb")`绕过预算。
- [x] 6.5 让Agent Write/Edit、输出选择和内部临时文件全部使用同一预算；输入用满40项后仍保留16个工作/输出和8个内部槽位，但容量不足时任何分区仍须在副作用前拒绝。
- [x] 6.6 对重复物化同一File/Version复用现有entry而不重复计数；对失败、取消、SHA-256不匹配、Runtime崩溃恢复和残留扫描验证文件与预留最终一致。
- [x] 6.7 同步Compose、环境示例、Runtime启动校验、readiness和非敏感诊断为64/224MiB及40/16/8分区；增加配置漂移时readiness失败的合同测试。
- [x] 6.8 增加自动物化、File MCP、Write/Edit、输出和tmp所有入口的数量/容量/并发边界测试，明确覆盖当前File MCP物化绕过缺陷。

## 7. Publication兼容门禁与租户上线

- [x] 7.1 将新搜索Tool加入兼容Agent Tool Envelope和文件提示，指导Agent按“冻结目录分页搜索→精确选择File/Version→准备物化”工作，不声明workspace/revision或读取未选中文件。
- [x] 7.2 更新Business Application草稿/发布校验：面向文件数上限超过20的工作区必须显式冻结新搜索Tool及必要File MCP Tool；tenant数量/字节配额和Job/Sandbox运行边界不得写入Publication。
- [x] 7.3 保持历史Publication在不超过20个ACTIVE文件时的Manifest-only兼容行为；超过20且缺少新Tool时在Job创建前返回`file_workspace_publication_upgrade_required`，不得生成不完整Manifest或动态晋升。
- [x] 7.4 实现tenant文件数从20或以下提升到20以上的只读兼容预检，列出不兼容启用Publication的安全身份并阻止提升；容量覆盖仍独立遵守tenant配置治理和10GiB硬上限。
- [ ] 7.5 先部署schema、File Service、Runtime、Tool与兼容Publication，并让现有tenant显式保持20个/100MiB；完成预检和证据后再把目标tenant改为200个/2GiB并记录配置审计。
- [x] 7.6 编写回滚手册：把tenant恢复到20个/100MiB、停止新兼容Publication流量，超限工作区保持已有内容可读但拒绝增加超限维度；保留历史revision、工作集与Job事实。

## 8. 验证、压测与真实E2E

- [ ] 8.1 建立200/1000 ACTIVE文件、2GiB默认/10GiB硬容量、50项冻结分页、40输入、64文件/224MiB Sandbox、并发Job和Docling状态压测，记录目录成员行数、Manifest字节、Job创建/搜索/预检P50/P95及数据库查询计划。
- [x] 8.2 证明1000文件工作区只绑定2项时Manifest不复制其余998项；同一Job在当前目录变化后分页稳定，新Job观察新revision，未选文件不进入Sandbox。
- [x] 8.3 运行File Workspace、Platform Config、Business Application、File MCP、Agent Worker和Python Runtime聚焦回归及完整后端测试，并执行前端静态检查、`docker compose config --quiet`、OpenSpec strict validation与`git diff --check`。
- [ ] 8.4 完成真实Runtime→冻结目录分页→精确选择→File MCP预算预留→Docling Markdown物化→Agent读取→回复或Delivery全链E2E；证明原始二进制和未选文件未进入Sandbox。
- [x] 8.5 保存File MCP在第41项、224MiB容量不足、下载失败和hash不匹配时于首字节前拒绝/清理/释放预留的证据；容器healthy或单元测试不得替代全链验收。
