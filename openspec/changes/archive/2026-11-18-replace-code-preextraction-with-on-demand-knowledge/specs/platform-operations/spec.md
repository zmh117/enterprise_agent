## MODIFIED Requirements

### Requirement: 知识存储通过统一来源身份和独立收录关系管理
系统 SHALL 以稳定来源、document、内容 revision 和独立知识库收录关系管理知识。平台 SHALL 保留逻辑知识库、身份/授权、资源发布、Job 与审计；内容 PostgreSQL 的 knowledge schema 和 Qdrant SHALL 支持当前平台本地存储或明确配置的独立内容连接。来源工作项身份 MUST 独立于知识库和可变类型，内容版本 MUST 可追溯；代码来源 SHALL 以仓库 UUID/分支/SVN revision 和业务问题/条件保留独立版本，并将问答记录与可复用知识分开；收录、离线导入或建立索引 MUST NOT 自动产生 Agent 或用户读取授权，不得自动建立、搬迁或写入外部内容库。

#### Scenario: 同一来源内容被多个知识库收录
- **WHEN** 相同来源工作项进入两个知识库
- **THEN** 系统复用稳定 document 和内容版本并建立不同收录关系，不复制来源文档

#### Scenario: 来源团队未确认
- **WHEN** 本地导出缺少可信团队或实例身份
- **THEN** 系统仅记录来源未确认的离线命名空间，不猜测或接续现有 ONES 身份

#### Scenario: 判断知识导入是否已提供检索能力
- **WHEN** 当前代码完成内容导入或向量索引
- **THEN** 该事实不代表对应资源、角色、应用或工具已经发布和获准；在线 MCP 目录与检索仍须执行独立授权；ONES 来源按当前模式核验本人 ONES 可读性，代码来源执行当前 KB/代码来源与版本策略

## ADDED Requirements

### Requirement: 代码知识结构必须区分版本身份与问答历史
系统 SHALL 将仓库、检出、资源配置、分析、SVN 操作、证据、答案、答案修订、问答记录和索引任务分开持久化，复用 source/document/document_revision/收录/分块/向量索引；code_answer 的稳定身份 MUST 由 source、数字 SVN revision、规范问题、业务条件与可见范围确定，不依赖 checkout、分析占用或 KB。不同 SVN 版本 MUST 建独立 document，同版本纠错 MUST 建新内容修订并通过预期 current_revision 检查更新；code_answer_revision 只容纳证据充分的修订，partial/conflicted 保留在 analysis/qa_record。每次最终回答与共享知识、向量派生 SHALL 分开保存，不能把问答日志直接作为确定知识。

#### Scenario: 不同版本存在相反规则
- **WHEN** r100 要求 A 非空而 r101 允许 A 为空
- **THEN** 两条规则分别具有独立版本身份和证据，纠正 r100 答案不会覆盖 r101，也不生成未核验的适用版本区间

#### Scenario: 同时修正同一答案
- **WHEN** 两个分析基于同一 current_revision 提交不同修正
- **THEN** 通过唯一身份与事务 CAS 检查拒绝过时覆盖，重放同一保存不重复创建修订或派生任务，不能以相似度自动合并不同条件

#### Scenario: 问答命中但未产生新知识
- **WHEN** 用户再次查询同 SVN 版本并使用当前已就绪答案
- **THEN** code_qa_record 记录本次允许保存的回答及真实版本引用，document/revision/chunks 保持不变，不调用 Embedding

### Requirement: 代码来源与分析持久化必须保持真实归属
code_repository SHALL 固定唯一仓库 UUID/分支，code_resource_config SHALL 扩展现有资源配置修订并绑定来源/受管目录，code_checkout SHALL 保存唯一物理工作副本身份与写者，code_svn_operation SHALL 承担 SVN 操作的幂等与恢复。code_analysis MUST 同时绑定真实 Job/invocation、来源、目标版本和独立读占用；code_evidence MUST 关联实际工具观察及可核实版本/路径/表示/hash。复用既有 invocation 归属与停止证明，不增加模型任务、快照目录或明文 grant 表。

#### Scenario: 多知识库使用同一来源或目录
- **WHEN** 两个代码 KB 引用相同仓库分支和同一工作副本
- **THEN** 共享 source/checkout 锁身份，通过独立配置和知识收录保持权限边界，不再限制一个 source 只能绑定一个 KB

#### Scenario: 逻辑终态但执行未停止
- **WHEN** analysis 或 SVN operation 已报告失败或租约到期，旧读取/子进程仍无法确认停止
- **THEN** 保留未释放读占用或目录写者，拒绝新写入；不能从终态/时间推导已经可更新

### Requirement: 代码答案派生必须使用独立持久任务而非伪造采集批次
代码内容修订 SHALL 以 code_analysis 标记真实来源，import 修订继续绑定 import_run；两种来源 MUST 恰选一种，不伪造 ONES 项目和采集信息。code_index_task SHALL 与新修订/收录变化同事务保存，使用固定 index/profile、唯一修订/动作身份和可恢复步骤复用现有派生执行能力，不依赖 ONES sync_run/sync_candidate。同 index/document 修改必须串行；当前性、收录、配置和停止恢复必须在派生及就绪前核实。查询 MUST 同时校验 PG 当前有效修订、受权收录、完整就绪与 Qdrant 可见标记。

#### Scenario: 纠错保存后索引未完成
- **WHEN** 新的正确修订已提交而索引仍失败或待处理
- **THEN** 旧错误修订退出当前检索，新修订待就绪；允许明确未命中或待索引，不返回旧错误答案，不重复模型分析

#### Scenario: 移除后重新收录
- **WHEN** 某修订从 KB 移除又重新收录，旧清理任务可能仍在恢复
- **THEN** 串行核对当前收录意图并恢复对应精确点，历史 succeeded 不冒充本次就绪，旧 remove 不得覆盖新的有效 upsert

### Requirement: 旧代码表退役不得破坏共享知识结构
新迁移 SHALL 按实际来源、依赖和写者清单退役 20 张旧代码专用表，重建 10 张代码表及所需共享字段约束；旧候选无须兼容或自动转换为新答案。执行前 MUST 排空旧代码写者、停用旧入口/发布并列出实际依赖及代码专属行；不得无范围 DROP CASCADE、删除 ONES/其他来源或已有工作副本文件。迁移 MUST 遵循当前 Migrator/catalog/事实源/中文注释及 SQLite 等价合同，不改已执行迁移；Qdrant 清理须独立幂等，不能宣称与 PG 具有原子事务。

#### Scenario: 共享表具有源码快照名称字段
- **WHEN** 退役 code_source_snapshot/code_snapshot
- **THEN** 只删除其专属结构和经确认引用，保留 ONES 使用的 document_revision.source_snapshot、import/sync、document_relation 和发布历史字段

#### Scenario: 旧检出任务表退出
- **WHEN** code_checkout_job 由 code_svn_operation 替代
- **THEN** 已完成的实际检出目录保持不变，经只读核实后登记为 code_checkout，不将旧候选搬迁成答案，也不补造一次成功的新 SVN 操作

#### Scenario: 验收数据库重建
- **WHEN** 宣称新代码数据库结构可用
- **THEN** 提供 PostgreSQL 迁移/约束/并发验证以及 ONES 和共享对象保留证据；OpenSpec 校验或 SQLite 测试不能代替这些证据

### Requirement: 受管检出目录必须直接只读提供给 Runtime
系统 SHALL 支持从现有已完成检出任务登记受管工作副本，绑定 source、仓库 UUID、分支、已选目录/文件范围和当前 revision。knowledge-sync 可写该工作副本；Runtime A/B MUST 将同一宿主检出根映射到固定容器路径并只读使用，不另建源码快照、封存副本、按版本目录或独立提取任务。登记不触发模型、不接受任意宿主路径；同一真实工作副本不能通过别名或重叠登记获得多个锁身份。模型只能读 grant 范围内的受支持文件，不能访问 .svn、未跟踪项、未授权 externals 或越界链接。

#### Scenario: 直接使用已检出工程
- **WHEN** 管理员登记已完成的 set_server/EBR/JTH 受管检出
- **THEN** 两个 Runtime 从相同检出根只读访问获准子集，不生成第二份代码，不需要配置独立提取应用

#### Scenario: 部分工程与目录别名
- **WHEN** 只检出 EBR，或试图用重叠路径再次登记同一工作副本
- **THEN** 前者允许使用但明确缺失后端/JTH；后者拒绝，不得借两个登记身份绕过互斥

### Requirement: 同版本分析共享读取而所有修改必须独占
系统 MUST 以持久的目录状态和每 Job 读占用协调并发。同一 checkout、同一已核实 revision、无写者时，多个合法 Job SHALL 可同时读取；实际 update、修复、删除或其他修改 MUST 同时满足无其他写者、无任何读者，修改期间禁止新读者。读者加入、写者取得、释放和写转读必须在同一目录身份上原子判定，不能仅使用进程内锁或 SVN 自身工作副本锁。所有平台入口、管理操作和定时任务均遵守该规则。

#### Scenario: 两个分析并发读取
- **WHEN** A/B 请求同一已核实 r100 工作副本且无写操作
- **THEN** 两者分别取得 r100 读占用并并发分析，条件/证据/授权独立，不为每个读者重复实际 update

#### Scenario: 更新遇到读者
- **WHEN** A/B 正在读取而任意入口请求实际 update 或切换版本
- **THEN** 修改被拒绝或报告 WORKSPACE_BUSY，全部读者释放前不得修改，即使仅剩一个读者也不得放行

#### Scenario: 两个更新和新读者竞争
- **WHEN** 一个 update 已取得独占，另一个 writer 或新读者同时请求进入
- **THEN** 后两者不能进入，更新核实完成并原子转为读占用或释放后才重新准入，不出现半更新读取

#### Scenario: 持读者要求切换版本
- **WHEN** 某 Job 已读 r100 又要求同一目录更新为 r101
- **THEN** 先结束本次分析并释放自己的读占用，再独立申请写；其他读者未结束时返回忙，不能持读等待升级或强制取消他人

### Requirement: 工作副本更新和异常恢复必须可核实
受控 update MUST 在独占期检查来源/范围、dirty/conflict/switched 状态并更新到显式数字 revision，禁止自动 revert 用户文件。只有全部选中项 operative revision 一致、内容可用且无异常才允许进入读取阶段；文件 last_changed_revision 较旧不算混合版本。成功 writer SHALL 原子转换为当前 Job 的读占用，不留抢写空档；同版本加入者只做只读检查。修改中断、授权撤销或来源变化必须停止执行，目录未核实前标不可分析。超时回收必须先确认相关 Runtime 在途读取和 SVN 子进程停止，不能仅凭 lease 到期放行写者。

#### Scenario: 更新到一半失败
- **WHEN** update 中断，部分文件 revision 已变化
- **THEN** 目录标失效，不发读取 grant、不假称原版或目标版完整；确认旧进程停止并受控修复、重新核实后才能使用

#### Scenario: 读者租约到期
- **WHEN** 一个读者过期但进程尚可能继续读取
- **THEN** 撤销新读取准入并恢复执行状态，写者继续被阻止；确认退出后只回收该读者，其他合法读者保持有效

#### Scenario: 幂等重放
- **WHEN** update/加入读取的响应丢失，同一合法请求重放
- **THEN** 返回原操作和同一读占用，不重复 update、不增加读者计数、不另起模型

#### Scenario: 宿主绕过平台修改
- **WHEN** 读取或保存核对发现版本/文件 hash 与本次受保护分析不符
- **THEN** 终止受影响分析并拒绝确定答案准入，工作副本重新核实前不可用，不认为只读挂载已经阻止所有外部写者

### Requirement: 代码结果必须按版本持久化且不依赖本地永久副本
系统 MUST 复用 document/revision/知识库收录模型保存问题级代码答案与必要分析记录。有效身份包括 source、仓库 UUID、分支、SVN revision、业务问题/条件和可见范围；checkout_id/占用代次仅用于执行追溯，不要求保留原目录版本。每项结论 SHALL 绑定真实读取的相对路径/行号/符号/hash/编码表示及必要 SVN 历史操作证据。不同版本独立保存，同版本纠错生成新修订；partial/conflicted 只存分析记录，不进入确定答案索引。验证来源不等于人工审批或生产事实确认。

#### Scenario: 目录更新后查询旧答案
- **WHEN** 本地目录已从 r100 更新到 r101
- **THEN** r100 答案仍有独立身份；复核其源码按仓库/分支/r100 路径重新取得并核对，不读取当前文件冒充旧证据

#### Scenario: 历史无法取得
- **WHEN** 原 SVN 仓库或对应历史已不可用
- **THEN** 明确历史证据暂不可复核，不伪造新版本依据；本地不为此隐式保存全量源码副本

#### Scenario: 条件或依赖不足
- **WHEN** 核验仍有关键配置/依赖未知，或只有私有单据实例信息
- **THEN** 保存未知范围，不能把猜测或实例值提升为共享确定规则，不复制整段聊天

### Requirement: 答案保存和索引必须独立于目录占用恢复
PG SHALL 为知识事实源，受控保存工具先停止本 Job 的新读取并等待其在途调用结束，在该 Job 读占用内验证后事务提交结果及索引任务；提交后仅撤销该 Job 的 grant 并释放其占用，其他读者不受影响。Qdrant 由现有 Worker 幂等派生，索引不占目录。语义搜索只返回已就绪向量并复核 PG 当前修订与授权；保存与索引状态分开表达。代码知识复用现有 PG/Qdrant 服务但保持独立来源、收录与集合，不修改 ONES 同步和数据。Runtime/MCP 不获得通用写库能力。

#### Scenario: Qdrant 失败
- **WHEN** PG 已提交而向量派生失败
- **THEN** 可返回已保存答案及索引待完成状态，目录占用已释放，Worker 只重试派生，不重复模型分析

#### Scenario: PG 保存失败
- **WHEN** 版本/证据校验通过但 PG 提交失败
- **THEN** 不声称已缓存；可给出本次有依据回答并说明未保存，Job 收尾仍停止读取并释放自己的占用

#### Scenario: 空库首次提问
- **WHEN** 来源/权限和空索引配置正常但没有答案
- **THEN** 返回合法未命中并允许原 Agent 查代码，不要求先导入全量业务知识包

### Requirement: 管理入口必须展示工作副本与分析状态
管理端 SHALL 在代码知识库配置内提供 SVN 地址、浏览、多选文件/目录与完整检出，并将该 KB 绑定到匹配来源的已完成检出，配置来源范围和用户 SVN 必填策略，展示实际 revision、多个读取占用、写者、更新进度、答案及索引状态。管理端修改遵守同一读写互斥。旧基线提取、整包候选发布和定时业务重建入口 MUST 退役；先排空写者、按清单处理旧候选，不兼容升级为新答案，不删除 ONES 或未明确退休的数据。新合同通过正式发布应用到两个 Runtime，不改写旧 Job。

#### Scenario: 管理员更新正在使用的目录
- **WHEN** 页面显示仍有两个分析读者，管理员点击更新
- **THEN** 显示目录忙且实际不修改，能区分读者数量和更新状态，不强制抢占

#### Scenario: SVN 出现新提交
- **WHEN** 仓库新增 revision 而尚无人提出需要新版本的问题
- **THEN** 不启动业务预提取；已有缓存保留原版本，任何独立源码更新仍遵守读写互斥

### Requirement: SVN 必须支持三平台统一挂载与执行
部署 SHALL 支持 Windows Docker Desktop/WSL2、macOS Docker Desktop、Linux Docker Engine 的 Linux 容器；SVN CLI 仅由执行器调用，不依赖宿主原生 SVN。相同 CODE_SVN_CHECKOUT_HOST_ROOT SHALL 可写挂给 knowledge-sync、只读挂给 Runtime A/B，固定容器路径为 /var/lib/code-svn/checkout。宿主路径只经 Compose 长格式 bind 映射并核实 daemon Mounts.Source；不硬编码盘符、用户名、网络或路径别名，缺失目录不得隐式误建。新流程不再依赖额外源码根挂载，凭据隔离沿用既有合同。

#### Scenario: 更新后读取同一目录
- **WHEN** knowledge-sync 在无读者时完成一次合法 update
- **THEN** 后续获准的 Runtime 从同一只读挂载看到新版本，无需复制快照或重新构建镜像

#### Scenario: 三平台验收
- **WHEN** 宣称可以跨平台部署
- **THEN** 分别提供真实 CLI、中文/空格路径、A/B 拒写、同版本并发读、读写/写写互斥及异常恢复证据，注明架构；不能用 Mac 单平台测试代替其他环境

### Requirement: 开源 SVN 后端复用不得绕过平台目录协调
系统 SHALL 保留开源 SVN MCP 的候选评估，只有固定许可/版本、输出界限、取消恢复及合同试验满足需求且减少维护成本时才采用；仅作为 knowledge-sync 内部固定后端，不新增 Runtime 可直连的公开入口或通用插件体系。平台 update、授权及读写协调 MUST 保持唯一控制入口，上游全部写工具和 prompts/resources 不得转发给模型。未采用时沿用现有受控 CLI，不同时维护多个可切换实现。

#### Scenario: 上游自带 update 和 snapshot
- **WHEN** 候选项目提供通用工作副本修改和状态摘要工具
- **THEN** 不允许它绕过平台占用更新目录，不因工具名称引入额外源码副本；只复用经固定合同验证的能力

### Requirement: 知识库创建与配置必须按 ONES 和代码类型区分
管理端 SHALL 提供 ONES/代码知识库类型选择，保留 ONES 的既有内容/采集配置；代码类型 SHALL 可创建空逻辑 KB，并配置 SVN 地址/分支/凭据引用、checkout 绑定、受管 PostgreSQL/Qdrant、分块/Embedding profile、增量索引与共享重排。不得要求代码用户先导入 ONES 内容或选择提取应用/账号。类型创建后不能在同一身份上直接互换；草稿/验证/发布与应用授权仍独立。页面 MUST 移除旧已登记源码快照、mes-code · SVN 与更新计划及顶层预提取面板，SVN 配置归入具体代码 KB。

#### Scenario: 创建空代码知识库
- **WHEN** 管理员选择代码类型，绑定匹配仓库/分支的已完成检出并配置受管存储/profile
- **THEN** 可保存草稿、显式初始化空增量 collection 并验证发布，零答案不是失败，不触发预提取或自动授权

#### Scenario: 类型表单与旧入口
- **WHEN** 新建或编辑 ONES/代码知识库
- **THEN** 代码配置不显示 ONES 身份/Team/采集日期，ONES 不要求 SVN；旧源码快照和更新计划入口不存在，也不继续请求旧构建列表

#### Scenario: 目录绑定不符
- **WHEN** 所选 checkout 的 UUID/分支与配置地址不一致，或分析中尝试换目录
- **THEN** 验证或重绑被拒绝，不以手工改标签冒充匹配，不自动移动/覆盖文件

#### Scenario: 共享同一工作副本
- **WHEN** 两个代码 KB 配置引用相同受管 checkout
- **THEN** 复用同一目录身份与读写协调，来源/知识收录仍分别校验，不创建第二条锁记录绕过占用

### Requirement: 代码存储配置必须绑定可写受管目标
代码 KB SHALL 默认复用既有受管 PostgreSQL、Qdrant 和 Embedding，保存目标引用、独立 collection、模型/维度/分块 profile 及当前配置修订。验证必须检查源码绑定、受管写入能力和 profile 一致性；不得因 ONES 自定义外部只读连接探测成功就自动写入外部库。初始化须显式、幂等且仅作用于本 KB 目标，不自动执行外部 DDL、覆盖他库集合或搬迁数据。普通新答案就绪不得要求重新发布；来源/连接/profile 变更须验证新配置，不让在途索引混用配置。

#### Scenario: 只读外部连接
- **WHEN** 代码配置选择了仅用于读取 ONES 的外部内容连接
- **THEN** 不将其当作自动问答写入目标，要求选择已登记可写受管目标，ONES 原读取合同不变

#### Scenario: profile 变更
- **WHEN** Embedding 模型/维度或分块参数改变
- **THEN** 显式准备兼容索引并验证切换，不将新旧维度/profile 混写；普通答案增加只做增量处理

### Requirement: 每次有效代码问答必须保存带版本的回答记录
宿主 SHALL 在每个已提供有效 SVN 版本且产生业务回答的代码 Job 收尾时，幂等保存受限问答记录，包括规范化问题、允许持久化的业务回答、KB、requested_revision、实际引用知识版本/ID、支持状态、Job/结果修订与时间；缓存命中同样记录，不依赖模型记得调用工具。记录不复制原始聊天/凭据到共享知识；未给版本的澄清不能伪造版本。问答记录与可检索知识 MUST 分开，只有新产生或实质修订且证据足够的知识进入索引。

#### Scenario: 同版本缓存命中
- **WHEN** 用户重复问同版本问题并复用已有答案
- **THEN** 保存本次问答记录并关联已有知识修订，不重复创建知识文档、分块或调用 Embedding

#### Scenario: 高版本线索与未知结论
- **WHEN** 问答引用 r101 线索但无法确认用户 r100 的规则
- **THEN** 记录 requested_revision=r100、实际线索版本=r101 及未确认状态，不生成 r100 的确定答案向量

#### Scenario: 记录失败
- **WHEN** PG 回答记录保存失败或响应丢失
- **THEN** 按 Job/结果身份幂等恢复并显示实际状态，不宣称已保存，不为补记录再次启动模型

### Requirement: 新知识必须经过增量分块编码和索引就绪校验
PG SHALL 先事务保存已验证知识修订与持久派生任务；Worker 只处理新建或实质修订答案，按当前分块 profile 保留结论/条件/适用范围，再调用兼容 Embedding profile，幂等写独立代码 Qdrant collection 并校验就绪。每块 MUST 绑定 KB/document/revision/chunk/profile、仓库/分支/SVN revision、支持状态与证据引用，身份和过滤字段由服务端生成。查询只接纳就绪且 PG 当前有效的修订。重复命中不编码，增量暂停保留待处理记录；失败不撤销已提交答案或误删其他 SVN 版本。

#### Scenario: 保存后某块编码失败
- **WHEN** PG 已保存答案而部分块的 Embedding/Qdrant 步骤失败
- **THEN** 保留可重试任务，未完成修订不进入候选，不报告索引就绪，不重跑代码分析

#### Scenario: 同版本纠错与其他版本
- **WHEN** r100 答案产生新内容修订
- **THEN** 只更新该知识修订的派生记录并按确定点 ID 清理旧块，r101 答案和 ONES 集合保持不变

#### Scenario: 共享重排与独立内容
- **WHEN** 代码与 ONES 都使用现有重排服务
- **THEN** 复用模型/profile/有界队列，数据集合与来源权限独立，分别验收检索效果和并发负载，不因共享服务混入他库候选


### Requirement: SVN 原文结果必须通过有界瞬时通道返回
knowledge-sync SHALL 在现有容器内提供仅项目内部网络可用的结果端点，由已认证控制面按已准入 operation_id 和执行代次读取，再经 knowledge-mcp 返回原 Job；不得发布宿主端口、注册额外面向 Agent 的 MCP 服务，或接受任意命令、路径和 URL。端点 SHALL 使用现有服务凭据机制，Runtime 不得获取此凭据。diff 原文、提交说明和源码响应 MUST 仅保存在有界进程内缓冲，单响应最多 512 KiB、总缓冲最多 8 MiB，期限不得超过原 Job 截止及 60 秒，不写 PG、磁盘和普通日志。PG 仅保存参数、状态、摘要和停止证明。

#### Scenario: 正常取回历史结果
- **WHEN** 原 Job 在有效授权和读取占用内取回已完成历史操作
- **THEN** 控制面和执行器核对 Job、来源、当前占用、owner/代次及截止后返回原文，数据库只保留安全元数据和摘要

#### Scenario: 缓冲过期或执行器重启
- **WHEN** 内存结果已丢失
- **THEN** update 不重放；固定只读历史请求仅可在原权限和截止内重新获取，摘要不符返回 CODE_HISTORY_RESULT_CHANGED，不把新响应当成原证据

#### Scenario: 撤权或缓冲超限
- **WHEN** 请求已撤权、取消、到期、代次不符或缓冲容量不足
- **THEN** 返回固定拒绝或容量错误，不泄露原文，不落盘兜底，也不据此提前释放目录占用
