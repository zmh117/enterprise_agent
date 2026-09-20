## ADDED Requirements

### Requirement: 知识资源配置只验证本地数据与索引，不要求 ONES 来源确认
保存、验证和发布 SHALL 不要求用户填写或确认 ONES 地址、实例或 Team，不要求导入确认 CLI、证明摘要、Job 或 ONES 凭据。系统 SHALL 从所选内容库已有 KB 成员派生导入来源，核对完整文档身份/修订/项目、READY 索引和 profile/hash；技术验证 SHALL 检查固定内部 Embedding、所选 Qdrant 兼容性与点数。外部 Provider 授权 SHALL 留在运行时逐项检查，不得用配置验证成功替代。

新资源修订 MUST NOT 创建虚假 CONFIRMED 来源或沿用历史来源确认门禁。历史绑定及资源/验证/发布证据原样保留；旧版本 MUST 重新保存、验证和发布，不自动改写 hash 或授权。source/KB 离线状态和 document/revision/chunk/point 身份及原 hash MUST 保持不变，不重编码。

#### Scenario: 没有来源确认记录
- **WHEN** 已入库 KB 和兼容 READY 索引可用，没有任何来源绑定或 ONES 身份
- **THEN** 有管理权限的用户可以保存草稿并完成本地技术验证及发布，不发出 ONES 请求、不要求地址/Team 或凭据

#### Scenario: 技术依赖不具备条件
- **WHEN** 数据成员/修订变化，索引不兼容，或 Embedding/Qdrant 不可用
- **THEN** 系统拒绝验证或发布，不能以移除来源确认为由跳过技术验证

#### Scenario: 历史配置升级
- **WHEN** 系统应用前向迁移
- **THEN** 历史来源绑定与发布/验证及外键保留；不自动发布，新草稿直接固定本地来源摘要

#### Scenario: 资源已发布但用户不可读
- **WHEN** 用户没有当前 KB grant，或本人 ONES 身份无效/工作项不可读
- **THEN** 系统拒绝访问或过滤候选，不返回未经双重授权的引用或缓存正文

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
knowledge-mcp、本地 Qdrant 和 Embedding SHALL 继续由可选 knowledge 部署单元管理，MCP/Embedding 地址固定，内容 PostgreSQL/Qdrant 可由有权管理员配置；未启用环境 MUST 不依赖这些服务或其新增服务凭据。治理元数据 SHALL 使用平台 PostgreSQL 的现有 knowledge schema 及现有 RBAC 事实源，通过前向 Migrator 和当前 schema catalog 交付，不修改历史迁移或自动搬迁/删除已有文本、分块和索引。新治理事实 MUST 默认未核验、未发布、无业务授权。

#### Scenario: 内容数据库与平台分开
- **WHEN** 管理员配置独立内容 PostgreSQL
- **THEN** API 验证、知识 MCP 与 ONES 内部核验使用同一内容绑定，平台库只保留逻辑 KB 及治理事实；目标库只要求兼容内容表和必要读取权限，不执行平台迁移或要求平台身份/Job 表

#### Scenario: 旧资源升级连接能力
- **WHEN** 执行新增连接配置的前向迁移
- **THEN** 旧配置字段为空并保留原连接、hash 与发布历史；解除资源修订到平台本地索引的外键，内容索引归属由用例核验，不自动发布新版本

#### Scenario: 管理或读写账号用于内容读取
- **WHEN** 有权管理员为知识内容配置管理员、所有者或具有写权限的 PostgreSQL 账号
- **THEN** 系统允许该账号按现有配置流程读取，不修改账号权限；当前目录、验证及检索连接仍使用并校验只读事务，保留固定内容查询与超时，不开放内容编辑或任意 SQL
- **AND** Knowledge MCP 的平台治理连接仍须使用固定最小权限角色，不因内容账号获准而放宽

#### Scenario: 内容连接故障或无法启用只读事务
- **WHEN** 内容库不可达、凭据停用或读取连接未处于只读事务模式
- **THEN** 拒绝访问并返回安全错误，不回退平台内容，不在平台事务中等待外部 I/O；平台资源列表与停用操作仍可使用

上线记录 MUST 分开列出合成/静态、容器/数据库、本地数据/索引验证、真实 ONES 本人权限、本地 Embedding 与现有聊天模型真实新 Job 证据。缺失真实 ONES 可读性、模型链路或人工标签时 MUST 保留未完成任务；健康容器、Mock、索引成功或 OpenSpec 校验不能替代这些门槛。回退 SHALL 停用新增读取入口而保留数据及既有会话访问/保留约束。

#### Scenario: 另一个环境不启用知识库
- **WHEN** 环境只启动原主系统部署
- **THEN** 不必启动 Qdrant/Embedding/knowledge-mcp 或配置其服务凭据，已有非知识功能保持兼容

#### Scenario: 新代码和迁移部署
- **WHEN** 用户批准正式部署知识检索功能
- **THEN** 先核对非终态工作、镜像与 schema 兼容，执行正式 Migrator 并验证 readiness，知识资源/授权/Publication 仍需显式配置

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
