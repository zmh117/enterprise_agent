## ADDED Requirements

### Requirement: 离线知识来源必须在导入侧显式确认后才能受治理回源
系统 SHALL 用独立、有修订和审计的来源绑定记录，将离线 source 显式绑定到受信 ONES 实例与 Team。允许发布前 MUST 在导入侧取得整个批次来源的明确确认，核对批次完整性与固定目标，记录 CONFIRMED、操作者、时间及系统生成的声明摘要，不将其标成 ONES 技术核验成功。Web MUST NOT 要求手填证明摘要或 RUNNING Job ID。历史 VERIFIED 与证据原样保留，PENDING MUST NOT 自动升级；发布仍需本地索引技术验证，每次命中仍需当前 KB＋本人 ONES 双重校验。抽样工作项存在、项目同名或索引完成 MUST NOT 单独证明全批次来源。来源撤销或换版 MUST 使依赖它的检索验证失效并重新发布。

既有离线 source 的 origin_state、存储 KB 状态、document/revision/chunk/point ID 及哈希 MUST 保持原导入/重放合同；新的检索发布状态 MUST 与存储状态分开表达。来源绑定 MUST NOT 保存凭据、原始业务消息或改写历史来源证据。

#### Scenario: 未核验离线批次
- **WHEN** 数据已经入库、分块和向量化，但没有明确实例/Team 的来源确认
- **THEN** 仍可做受限离线运维检查，但不得发布成真实用户 ONES 检索资源

#### Scenario: 建立合法来源绑定后重放
- **WHEN** 导入侧显式确认并新增来源绑定，随后重放同一导入或索引
- **THEN** 原 source/KB/document/chunk/point 身份及幂等校验保持有效，不因治理绑定而重复建文档或重算向量

#### Scenario: 更换 ONES 来源
- **WHEN** 操作者需要调整绑定的实例或 Team
- **THEN** 系统保留旧修订，要求新修订来源确认和资源重新验证发布，不直接覆盖历史或复用旧技术验证

#### Scenario: 导入侧确认不需要运行中的业务任务
- **WHEN** 有效平台管理员通过受限导入后入口显式确认完整批次的固定 ONES 实例与 Team
- **THEN** 系统生成可审计 CONFIRMED 绑定，不要求 Job、Token 或手填摘要，不调用 Provider，不自动发布或授予业务权限

#### Scenario: 已确认来源仍须本人逐项权限检查
- **WHEN** 当前应用用户检索来源已确认的知识库
- **THEN** 系统仍核验有效 RUNNING Job、KB 授权、本人 ONES 实例/Team 及工作项当前可读性，不将导入管理员的确认当作用户授权

### Requirement: 知识检索效果必须使用独立人工标注基线
系统 SHALL 提供本地评测集格式、校验和可重放评测入口，首批真实效果验收使用约 50 条人工确认问法，包含 query_id、KB/来源、人工相关文档标注、无答案标记、分类和标注来源。真实问题与标签 MUST 保存在受限本地目录，不进入 Git、通用日志、外部模型或外部遥测；仓库 SHALL 仅保存合成样例和脱敏汇总。缺失标签 MUST NOT 用模型生成、自查询命中或相似度阈值冒充。

报告 MUST 区分原文自查询、合成合同测试、离线 dense 基线和真实用户双权限端到端效果，记录评测集/语料/索引/profile/hash、代码版本、检索参数和运行环境。Recall@10 MUST 按文档去重后命中的相关文档比例计算；MRR@10 MUST 用首个相关命中的倒数排序且未命中为零。无答案样本 SHALL 独立报告误报，不进入空相关集的召回分母；标注不穷尽时 MUST 明确仅为标注集内指标。

#### Scenario: 有相关项和无答案混合评测
- **WHEN** 集合包含多个相关文档、重复块命中和无答案问题
- **THEN** runner 按文档统计 Recall@10/MRR@10，重复块不增加召回，无答案单独报告

#### Scenario: 只有原文自查询证据
- **WHEN** 索引原文自查询全部首位命中，但没有人工改写问题及相关性标注
- **THEN** 只报告管线探针成功，不声称真实业务召回率达标

#### Scenario: 比较不同用户的检索效果
- **WHEN** 两位用户当前 ONES 可读范围不同
- **THEN** 端到端评测分别以各自当前可读的标注相关集合计算，记录授权观察时间/版本，不通过返回未授权文档提高召回率

### Requirement: 知识性能与故障验收必须包含权限链路
知识评测 SHALL 同时记录纯检索耗时和包含可读性检查/必要详情访问的端到端 p50/p95、partial 比率及安全失败分类，区分检索未命中、来源不一致、授权拒绝、身份失效、Provider 故障和固定预算截断。效果与时延准入值 MUST 在实测基线后由用户确认，尚未确认时只报告基线，不能编造达标结论或承诺更大语料容量。

#### Scenario: 检索快但 ONES 校验慢
- **WHEN** Qdrant 返回迅速，而本人详情可读性检查导致显著延迟或限流
- **THEN** 报告端到端延迟和 Provider 分类，不把纯向量检索耗时当用户体验

#### Scenario: 缺少准入阈值
- **WHEN** 已运行评测但用户尚未确认质量与时延目标
- **THEN** 保留实测基线和失败清单，不标记业务效果验收达标

### Requirement: 知识服务必须可选部署并保留真实验收缺口
knowledge-mcp、Qdrant 和本地 Embedding SHALL 继续由可选 knowledge 部署单元管理，固定内部地址和受管凭据；未启用环境 MUST 不依赖这些服务或其新增服务凭据。治理元数据 SHALL 使用同一 PostgreSQL 的现有 knowledge schema 及现有 RBAC 事实源，通过前向 Migrator 和当前 schema catalog 交付，不修改历史迁移或自动迁移/删除已有文本、分块和索引。新治理事实 MUST 默认未核验、未发布、无业务授权。

上线记录 MUST 分开列出合成/静态、容器/数据库、来源证明、真实 ONES 本人权限、本地 Embedding 与现有聊天模型真实新 Job 证据。缺失来源、真实模型链路或人工标签时 MUST 保留未完成任务；健康容器、Mock、索引成功或 OpenSpec 校验不能替代这些门槛。回退 SHALL 停用新增读取入口而保留数据及既有会话访问/保留约束。

#### Scenario: 另一个环境不启用知识库
- **WHEN** 环境只启动原主系统部署
- **THEN** 不必启动 Qdrant/Embedding/knowledge-mcp 或配置其服务凭据，已有非知识功能保持兼容

#### Scenario: 新代码和迁移部署
- **WHEN** 用户批准正式部署知识检索功能
- **THEN** 先核对非终态工作、镜像与 schema 兼容，执行正式 Migrator 并验证 readiness，来源/授权/Publication 仍需显式配置

#### Scenario: 合成测试通过但真实前提缺失
- **WHEN** 测试全部通过，但没有真实 ONES 可读性或已配置聊天模型的新 Job 证据
- **THEN** 只记录工程验收完成，真实 Agent 链路和对应任务保持未完成

### Requirement: 知识模块必须按职责分层且保留已有数据身份
knowledge SHALL 按 api/application/domain/infrastructure 分离。domain MUST 只包含规则和数据合同，不执行数据库、HTTP 或文件 I/O；application MUST 通过当前用例所需端口访问存储和外部服务，不直接写 SQL、读取数据库属性或构造网络客户端。SQL、事务实现、文件、HTTP 与具体依赖装配 SHALL 留在 infrastructure 或组件入口。

重构 MUST 保持既有文档/修订/分块/点 ID、内容 hash、Embedding profile、事务与断点续跑语义，不触发数据迁移、重导入或重编码。系统 MUST NOT 为分层引入无当前调用者的通用 CRUD 框架或插件扩展层。

#### Scenario: 规则或用例引入基础设施依赖
- **WHEN** domain 导入 SQL/HTTP/文件组件，或 application 直接访问数据库或构造客户端
- **THEN** 架构回归阻止该依赖，规则与实现不能只靠文件夹名称区分

#### Scenario: 重构后重复导入和索引重放
- **WHEN** 使用同一批输入、版本和索引重放
- **THEN** 原身份与 profile/payload 保持一致，保留幂等、回滚与 checkpoint 行为，代码实现指纹允许如实变化
