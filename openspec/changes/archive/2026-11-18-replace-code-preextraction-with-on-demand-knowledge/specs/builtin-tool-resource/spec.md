## MODIFIED Requirements

### Requirement: 知识资源与固定目录检索必须执行当前双重授权
系统 SHALL 通过已验证、已发布且当前启用的知识资源和代码固定 `knowledge_list_bases`、`knowledge_search` 提供入库内容读取。发布 SHALL 只确认知识库及其来源、存储、模型和分块配置可用，不冻结成员、数量或内容摘要；正常内容更新不得改变发布修订或要求重新发布。Knowledge MCP MUST 验证自身 audience/scope、RUNNING Job、冻结工具合同、当前用户/应用/角色 KB 范围及资源发布配置；命中 MUST 再校验当前知识库成员、文档修订和索引证据。部署配置 `KNOWLEDGE_ACCESS_MODE` SHALL 仅接受 `online` 或 `offline`，未设置时默认 `online`，非法值 MUST 阻止启动。对于 ONES 来源，在线检索 MUST 在平台知识库授权基础上逐项核验本人 ONES 当前可读性，403/404 项不得返回，身份、权限或服务核验失败 MUST 整次报错，禁止自动降级；只有显式 `offline` 才仅依据知识库授权读取入库内容，不依赖 ONES。代码来源 MUST 采用当前知识库授权、发布的代码来源/业务投影策略和固定源码版本范围，不依赖个人 ONES 身份，也不得借代码来源绕过 ONES 访问拒绝。模型参数 MUST NOT 覆盖部署模式或来源身份。目录仅表示平台 KB 可见性，不保证在线命中均可读。新工具、收录、索引和目录变化 MUST NOT 自动扩大旧 Publication 或 Job 的知识库范围；内容返回合同变更 MUST 更新正式发布，不改写历史快照。

#### Scenario: 发现当前知识库
- **WHEN** 当前 Job 获准调用知识目录
- **THEN** 每页最多返回 50 个当前可用知识库的安全身份、名称和状态，提供有界续页，不返回正文或文档计数

#### Scenario: 授权或发布配置变化
- **WHEN** 用户/应用/角色 KB 权限撤销、资源停用或发布配置变化
- **THEN** 目录或检索失败关闭，不回退旧配置；普通内容更新不触发发布配置变化错误

#### Scenario: 显式离线模式
- **WHEN** 部署显式配置 offline，用户和业务应用具有该知识库权限，但 ONES 不可达、未绑定本人身份或未授权详情工具
- **THEN** 目录与检索仍可返回该库当前有效的入库内容，查询路径不调用 ONES

#### Scenario: 默认在线模式与故障拒绝
- **WHEN** 配置未设置或为 online，ONES 来源的身份、当前权限或来源服务核验失败
- **THEN** 检索整体失败，不降级返回离线内容；只有明确通过逐项核验的命中才可返回

#### Scenario: 非法部署配置
- **WHEN** 配置为空、拼写错误或不是 online/offline
- **THEN** 知识服务拒绝启动，不选择较宽松的模式

#### Scenario: 当前成员或修订变化
- **WHEN** 检索途中知识库授权被撤销、命中文档被移出库或修订与索引证据变化
- **THEN** 返回前复核失败并丢弃整次结果，不返回跨库或过期修订内容

#### Scenario: 内容独立生效
- **WHEN** 已发布知识库新增文档完成向量处理
- **THEN** 该文档可参与检索，资源发布修订及未变更文档保持不变

#### Scenario: 代码知识不依赖个人 ONES 身份
- **WHEN** 用户只有代码知识库与业务投影的合法权限且未绑定 ONES
- **THEN** 系统按代码来源策略提供授权的版本化结论，不调用 ONES，不向用户开放源码目录或其他来源内容

### Requirement: 知识检索必须有界且明确返回入库内容快照
`knowledge_search` SHALL 接受明确 `knowledge_base_id`、1–2000 字符非空查询和默认 10、范围 1–20 的 `top_k`，不得允许覆盖身份、Team、filter、collection、向量或服务地址。代码来源 MUST 要求用户显式提供数字 SVN revision，并支持固定 exact/next_higher_hint 两阶段查询，由服务解析发布来源下的仓库/分支与候选版本，模型不得设置索引过滤表达式。目录和检索 SHALL 受最多 360 秒及当前 Job 剩余预算共同约束。ONES 检索 SHALL 返回文档/修订/索引/来源/工作项引用、原来源编号、完整标题、原状态、来源项目、来源更新时间、入库时间、排序和每项最多三条带位置/hash 的已入库文本片段；每片段最多 1200 字符，总响应最多 512 KiB，超限明确失败，不悄悄丢弃标题。代码检索 SHALL 在相同 top_k、片段及总响应边界内返回答案/修订/来源/索引引用、标题、结论支持状态、适用条件摘要、覆盖与未知项标记、已解析 SVN 身份及证据投影引用；片段不得冒充完整规则。结果 MUST 标明来源对应的 `access_mode`、`ingested_snapshot` 与 `matched_chunks`，不得宣称完整文档、来源最新状态或完整检索结果；入库时间不得冒充来源更新时间或最近采集时间。零命中、受限部分结果和依赖失败 MUST 分别表达，认证材料、查询原文和业务正文不得复制到普通安全摘要或日志。ONES 在线模式复用当前用户已授权的 ONES 详情能力作实时可读性核验，通过后仍返回带来源时间和入库时间的快照片段；实时权限不意味着快照是最新正文。离线模式不要求 ONES 详情能力。代码检索 MUST NOT 因版本缺失隐式申请整版业务预提取。

#### Scenario: 合法检索
- **WHEN** 合同、索引与当前知识库权限均有效且存在命中
- **THEN** 按来源与部署模式完成所需权限核验后返回当前入库修订的有界内容片段和元数据，说明实际模式、快照时间与范围

#### Scenario: 预算或依赖失败
- **WHEN** 总预算耗尽、依赖异常或读取投影不完整
- **THEN** 返回稳定失败；正常有界搜索产生部分结果时明确 `partial`，不能将依赖失败报告为空库

#### Scenario: 代码版本尚无答案
- **WHEN** 固定 SVN 版本下没有已就绪答案，但来源和检索服务正常
- **THEN** 返回带固定版本的正常未命中事实，不申请整版构建；后续只能通过单独授权的问题核验操作补充证据

## ADDED Requirements

### Requirement: 代码问答必须提供用户指定的 SVN 版本
代码问答 MUST 在用户提供明确数字 svn_revision 后才进行知识检索或源码分析；缺失时返回 SVN_REVISION_REQUIRED 并引导补充，不能用默认配置、现场绑定、checkout 当前版本或 HEAD 代替。来源/仓库 UUID/分支由发布的代码 KB 配置确定；查询、更新、保存及回答必须保留用户 requested_revision。直接复用的答案 MUST 同时满足相等版本、当前权限、有效知识修订、业务条件和足够证据，不凭相似度跨版本认定规则相同。

#### Scenario: 未提供版本
- **WHEN** 用户询问代码业务规则但未给 SVN 数字版本
- **THEN** 先要求补充，不检索、update 或创建带猜测版本的缓存；页面和 Skill 都提示版本必填

#### Scenario: r100 与 r101 不同
- **WHEN** 用户明确询问 r100，而缓存中 r101 允许 A 为空
- **THEN** r101 不作为 r100 的直接答案，响应和最终知识始终分别标明请求版本与证据版本

#### Scenario: 目录已更新
- **WHEN** 本地目录从 r100 更新到 r101 后用户查询已有 r100 答案
- **THEN** r100 可按自身身份及适用条件复用，不要求工作副本停在 r100，不读取当前文件冒充旧证据

### Requirement: 版本回退必须只提供最近更高版本的核验线索
knowledge_search MUST 先执行 exact 并用 svn_revision=N 硬过滤；无适用证据时才允许 next_higher_hint，关联同 Job 的成功 exact search_id、相同 KB/问题/用户版本和缺证据理由。服务端 SHALL 从同仓库/分支及当前授权、就绪知识版本中选择最小 R>N，只查询该版本一次；无相关线索时转查 N 的源码，不无限遍历其他版本或自动查较低版本。回退结果 MUST 包含 requested_revision=N、matched_revision=R、match_kind=higher_revision_hint、requires_verification=true 及差值。完整答案读取也必须保留搜索上下文和这些标记，不能通过直接读答案 ID 消除核验要求。相等结果与较高结果不混合排序。

#### Scenario: 选择最近更高版本
- **WHEN** r100 无适用证据，同来源授权就绪版本中有 r101 和 r105
- **THEN** 只将 r101 的相关命中作为线索，即使 r105 相似度更高也不越过版本选择；r101 无相关线索则查 r100 代码

#### Scenario: 高版本规则与目标相反
- **WHEN** r101 线索允许 A 为空，而实际核验 r100 要求非空
- **THEN** 最终回答与新知识保存 r100 的真实规则，r101 原记录保持原身份，不把较高答案复制成 r100

#### Scenario: 无法核验用户版本
- **WHEN** 只能找到较高版本线索且 r100 不可取得、无代码权限或关键证据不足
- **THEN** 明确不能确认 r100，不直接将 r101 的结论作为 r100 答案，不写入 r100 的确定答案索引

#### Scenario: 前置故障或越权版本
- **WHEN** exact 阶段故障，或较高版本仅存在于未授权 KB/分支
- **THEN** 故障不转成无命中；越权版本既不能被选择也不能泄露存在性，两个阶段共用总预算

### Requirement: 查代码必须由同一问答 Job 在知识证据不足后执行
系统 SHALL 先通过知识检索检查同版本答案，正常未命中、条件不符、关键证据不足或冲突时，才允许当前问答 Agent 使用来源授权的 SVN 工具和源码读取。`knowledge_svn_update` MUST 关联同 Job 的成功检索记录、相同知识库/来源/requested_revision/问题及缺证据理由，重新检查当前用户/应用/角色与来源策略。核验 MUST 在原问答 Job 中执行，不创建独立提取 Agent、专用服务账号 Job 或整包构建。访问拒绝、索引故障和依赖失败不能作为代码兜底理由。

#### Scenario: 首次问题无答案
- **WHEN** 合法检索在确定版本下正常未命中且应用允许代码分析
- **THEN** 原 Agent 请求更新/检查工作副本并在授权后读取代码，同一 Job 输出回答，不派发另一模型任务

#### Scenario: 命中但缺条件
- **WHEN** 检索结果缺少当前问题的关键分支证据
- **THEN** 可关联该成功搜索进行补证，不能只因存在相似文本就阻止查代码

#### Scenario: 检索失败或请求改变版本
- **WHEN** 前置搜索失败或 update 请求与搜索的知识库/来源/版本不一致
- **THEN** 拒绝读代码准入，保留原失败或要求对正确版本重新检索，不绕过权限和版本选择；较高版本线索的 matched_revision 不能成为 update 目标

### Requirement: SVN 工具必须复用固定 Knowledge MCP 和执行器
系统 SHALL 在现有 Knowledge MCP 提供 `knowledge_svn_update`、`knowledge_svn_info`、`knowledge_svn_log`、`knowledge_svn_diff`、`knowledge_svn_blame`、`knowledge_get_source_operation`，通过已认证控制面桥接交由 knowledge-sync 执行。工具 MUST 仅接受已登记知识库/来源/checkout、受控相对路径、版本/时间/行范围及操作标识，不接受任意 URL、宿主路径、凭据、可执行文件或 Shell 参数。update SHALL 声明受限工作副本修改副作用，在正式发布与来源授权下自动执行，但不提供仓库 commit/merge/revert/switch 或业务 mutation 确认豁免。

#### Scenario: Runtime 请求更新
- **WHEN** Agent 请求将已登记工作副本更新到确定 N
- **THEN** knowledge-sync 在取得独占写权限后执行固定参数 update，Runtime 自身只读挂载不变；若已在 N 且无写者则只检查并加入共享读取，不实际 update

#### Scenario: 同一目录已在分析
- **WHEN** 多个分析持有 N 的读占用，又请求实际 update 或切换到 N+1
- **THEN** 修改请求返回 WORKSPACE_BUSY；其他获授权 N 版本分析仍可共享读取，不抢占现有读者

#### Scenario: 非法目标
- **WHEN** 参数含任意绝对路径、未登记仓库、路径穿越或命令串
- **THEN** 在执行前拒绝，不将模型输入拼接为 Shell 命令

#### Scenario: 提交包含越权路径
- **WHEN** log -v 同时包含授权范围外的路径或复制来源
- **THEN** 返回前过滤并标明范围限制，无法安全投影的提交说明省略，不能沿复制信息越权读取

### Requirement: SVN 历史必须明确时间修订与文件身份语义
log SHALL 支持最近 N 次、单 revision、含两端 revision_range、明确时区的 time_range，并可限定文件/目录；返回授权内的 revision、时间、作者、说明及 A/M/D/R 路径。时间 SHALL 按实际提交时间的半开区间过滤，日期范围包含用户选择的结束日全天，不能假设 revision 时间单调。每次分析的数字版本上限、peg 和历史范围 MUST 固定，分页不得漂移；缺失元数据明确未知。info SHALL 区分仓库 revision、文件 last_changed_revision、选中项 operative revision 范围及 mixed/modified/switched。

#### Scenario: 最近一百条与分页
- **WHEN** 查询最近 100 次提交且查询后出现新提交
- **THEN** 结果同时包含允许的时间/作者/说明/文件列表，续页保持原数字上限，不混入新 revision

#### Scenario: 包含结束日
- **WHEN** 查询 Asia/Shanghai 下 2026-10-01 至 2026-11-09
- **THEN** 使用 [2026-10-01T00:00:00+08:00,2026-11-10T00:00:00+08:00)，不漏掉结束日白天，不把日期定位得到的区间外提交当命中

#### Scenario: 含端点范围与升级新增提交
- **WHEN** 查询 51000..52089 日志或询问从 51000 升到 52089 新增的提交
- **THEN** 前者包含两端，后者使用 51001..52089；返回实际覆盖，不能用端点 diff 代替提交记录

#### Scenario: 本地 import 不含原历史
- **WHEN** 本地 SVN 只包含 import 后的新历史而请求原公司 revision
- **THEN** 根据真实 UUID 和历史起点报告不可用，不伪造本地与原仓库数字版本的对应关系

### Requirement: 差异和行归属必须绑定确定版本并有界返回
diff SHALL 支持单提交 N-1→N、明确两端 revision 的文件摘要/单文件文本，不比较未提交本地修改；blame SHALL 使用指定版本的原文件行号。结果 MUST 关联实际路径、两端/peg、观察时间与摘要；处理删除重建和授权内重命名，不隐式回退 HEAD。log 默认 100、每页最多 200 条；diff 文本最多 256 KiB、blame 每次最多 400 行，MCP 响应最多 512 KiB，所有命令受执行时间及 Job 剩余预算约束。超限、不可用、部分覆盖和无变化 MUST 分别表达，cursor 绑定授权/路径/版本/筛选与结果身份。

#### Scenario: 修改后恢复原样
- **WHEN** 两端内容相同但中间存在修改提交
- **THEN** diff 可为空、log 仍有历史，Agent 不据空 diff 宣称期间没有变化

#### Scenario: 文件重建与行归属
- **WHEN** 同路径被删除重建或 blame 显示格式调整提交
- **THEN** 使用 peg/operative 区分对象；行最后修改归属不能单独证明业务变化点或个人责任

#### Scenario: 超限或游标越界
- **WHEN** 大型提交达到路径/时间预算，或 cursor 被用于另一版本/权限范围
- **THEN** 前者明确 partial/paths_truncated 及实际覆盖，后者拒绝，不输出伪完整证据

### Requirement: 结果保存必须通过受控答案工具校验证据
系统 SHALL 提供 `knowledge_save_code_answer`，接收当前 analysis_id、幂等键及有界的结论/条件/证据引用/覆盖/未知项，在有效读取占用内完成版本和实际工具读取记录核对后保存。Job、仓库、版本和验证状态 MUST 来自服务端绑定，模型不得覆盖或直接写库。该工具声明受限知识派生副作用，沿用当前发布/来源策略；一次分析完成后撤销该 Job 的 grant 并只释放其读占用，不影响其他读者。数据保存与向量就绪 SHALL 分开返回；partial/conflicted 不进入确定答案索引。

#### Scenario: 有证据的结论保存
- **WHEN** 原问答 Agent 提交条件完整且证据可核实的结果
- **THEN** 校验和 PG 提交在读占用释放前完成，返回答案引用及 SVN 版本，其他读者继续；模型不执行 SQL/Qdrant 写入

#### Scenario: 伪造证据或目录变化
- **WHEN** 引用未读取文件、错误行号/hash、其他 Job 的证据或本地版本已变化
- **THEN** 拒绝准入，不将其标为确定答案；必要时终止受影响分析

#### Scenario: 成功响应丢失
- **WHEN** PG 已提交并释放本次占用，原合法 Job 重放相同保存请求
- **THEN** 返回已提交的相同结果，不重新读目录、生成重复答案或重复模型执行

### Requirement: 完整答案必须提供当前授权的业务投影
`knowledge_get_code_answer` SHALL 返回最多 512 KiB 的完整结论、条件、覆盖、未知项、支持状态、SVN 身份与证据引用，超限明确失败或有界续取，不能省略条件后声称完整。读取代码答案须关联本 Job 的合法搜索结果并保留 requested_revision/matched_revision 和 requires_verification；源码正文、内部路径与历史明细须独立授权，普通用户只获得发布允许的业务投影。Agent MUST 区分代码规则、未知现场配置和生产事实，返回前复核当前修订及权限。

#### Scenario: 搜索片段遗漏配置例外
- **WHEN** 片段相关但完整答案包含影响结论的配置分支
- **THEN** 读取完整答案后再回答，保留例外与 SVN 版本

#### Scenario: 答案已纠正或撤权
- **WHEN** 答案修订被替代或来源/调用者权限撤销
- **THEN** 不返回旧修订或源码作为兜底，按当前有效状态重新检索

### Requirement: 重排必须在来源权限与版本筛选后执行
ONES 与代码检索 SHALL 复用已配置的固定重排服务与有界合同；候选进入重排前必须完成各自来源/KB/权限/版本过滤，代码 exact 与 higher hint 分阶段重排，重排分数不能覆盖版本优先级或免除目标版本核验。服务忙、超时或配置不符必须保留失败事实，不能作为零命中转源码兜底。

#### Scenario: 高版本分数更高
- **WHEN** r100 相等版本有适用答案而 r101 文本更相似
- **THEN** 仍使用 r100，不将 r101 混入同批排序或据高分直接覆盖 r100

#### Scenario: 共用服务繁忙
- **WHEN** ONES 与代码候选同时请求重排导致预算耗尽
- **THEN** 返回受限繁忙/超时事实，不误判知识不存在，审计不记录候选正文
