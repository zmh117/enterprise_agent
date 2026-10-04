## MODIFIED Requirements

### Requirement: JavaScript构建入口必须区分实际依赖锁与执行命令
系统 SHALL 将管理 Web 的 Makefile、GitHub CI 和容器构建统一到所在包的 `package-lock.json` 与 `npm ci`。维护者 MUST 核对具体工作目录、锁文件和命令；文档同步不得自动更新依赖或锁文件，钉钉 Runtime 与 Inspector 继续使用各自包的 npm 锁文件。

#### Scenario: 复现前端检查
- **WHEN** 维护者执行 `make frontend-check`
- **THEN** 按 `frontend/package-lock.json` 执行 npm 安装、lint、类型检查、测试与构建，与 CI 和容器使用同一依赖事实

#### Scenario: 判断CI通过范围
- **WHEN** 维护者查看某个 GitHub job 结果
- **THEN** 以 job 实际工作目录、锁文件和命令为准，不把一次入口成功当成所有入口通过

### Requirement: 知识存储通过统一来源身份和独立收录关系管理
系统 SHALL 以稳定来源、document、内容 revision 和独立知识库收录关系管理知识。平台 SHALL 保留逻辑知识库、身份/授权、资源发布、Job 与审计；内容 PostgreSQL 的 knowledge schema 和 Qdrant SHALL 支持当前平台本地存储或明确配置的独立内容连接。来源工作项身份 MUST 独立于知识库和可变类型，内容版本 MUST 可追溯；收录、离线导入或建立索引 MUST NOT 自动产生 Agent 或用户读取授权，不得自动建立、搬迁或写入外部内容库。

#### Scenario: 同一来源内容被多个知识库收录
- **WHEN** 相同来源工作项进入两个知识库
- **THEN** 系统复用稳定 document 和内容版本并建立不同收录关系，不复制来源文档

#### Scenario: 来源团队未确认
- **WHEN** 本地导出缺少可信团队或实例身份
- **THEN** 系统仅记录来源未确认的离线命名空间，不猜测或接续现有 ONES 身份

#### Scenario: 判断知识导入是否已提供检索能力
- **WHEN** 当前代码完成内容导入或向量索引
- **THEN** 该事实不代表对应资源、角色、应用或工具已经发布和获准；在线 MCP 目录与检索仍须执行独立授权及当前 ONES 可读性检查

### Requirement: 知识 schema 必须纳入现有迁移与事实源治理
平台本地 knowledge DDL MUST 仅通过一次性 Migrator 的版本化事务执行。结构、约束、索引、注释和事实源清单 MUST 覆盖当前 public 与 knowledge 对象；SQLite 测试 SHALL 保持等价领域对象且不得影响现有表。导入器 MUST 只检查 schema head，不执行迁移；独立内容连接 MUST 按当前内容合同校验，不要求外部库拥有平台身份、Job 或平台 migration ledger，也不得由在线读取服务自动建库或搬迁。

#### Scenario: 新 schema 建表后验收
- **WHEN** 新迁移执行完成
- **THEN** 校验以当前 migration catalog 和事实源清单为准，覆盖来源、版本、收录及后续分块、索引、同步等已纳入 catalog 的对象，不沿用初始七张表的数量作为当前完成标准

#### Scenario: 独立内容库尚未准备
- **WHEN** 管理员配置的内容连接不满足当前读取合同
- **THEN** 验证或读取失败关闭，不在服务启动和查询中执行外部 DDL

## ADDED Requirements

### Requirement: 镜像构建必须依赖静态与管理Web质量门禁
CI 的运行镜像构建 SHALL 仅在后端 lint、格式和类型检查、管理 Web lint/类型检查/测试/构建及既有运行合同门禁成功后执行。PR MAY 按既有规则跳过完整后端回归，但 MUST NOT 将静态或前端失败/跳过解释为通过。

#### Scenario: 静态或管理Web检查失败
- **WHEN** 后端静态检查或管理 Web job 失败
- **THEN** 运行镜像构建不执行

#### Scenario: PR仅跳过完整后端回归
- **WHEN** PR 的完整后端回归按规则跳过且其它必需 job 成功
- **THEN** 运行镜像构建仍可执行，不降低其它门禁

### Requirement: 管理页面必须按路由加载并保留权限与恢复边界
管理 Web SHALL 延迟加载目标路由页面，受保护页面 MUST 在现有 capability 校验通过后才开始页面加载。加载期间 SHALL 显示中文状态，页面模块加载失败 SHALL 进入现有错误恢复界面；认证、权限拒绝、路由地址及页面数据合同 MUST 保持原有行为。

#### Scenario: 无页面权限
- **WHEN** 当前用户缺少目标页面的 capability
- **THEN** 展示现有无权限状态且不开始加载该页面模块

#### Scenario: 首次进入合法页面
- **WHEN** 权限校验通过但页面模块尚未完成加载
- **THEN** 平台壳保留并显示中文加载状态，加载完成后显示目标页面

#### Scenario: 页面模块加载失败
- **WHEN** 页面块下载或导入失败
- **THEN** 展示现有可刷新、返回工作台的错误恢复界面，不伪装为无权限或空数据

### Requirement: 知识分块与本地向量索引必须保持固定身份及显式激活
系统 SHALL 提供受限文本分块、固定 BGE-M3 模型的本地 CPU Embedding 与独立 Qdrant 索引流程。模型 revision、文件摘要、架构依赖锁与 profile SHALL 可校验，分块/索引代际 SHALL 可追溯；建立候选或 READY 索引 MUST NOT 自动切换既有发布资源或扩大读取权限。模型准备、运维索引和常驻在线服务 SHALL 通过可选 Compose 扩展明确区分。

#### Scenario: 准备与重建索引
- **WHEN** 操作者显式准备固定模型并对指定候选建立索引
- **THEN** 系统校验固定 profile、容量及代际完整性，保留既有可用索引与资源直到明确激活

#### Scenario: 仅启动基础平台
- **WHEN** 部署未加载知识 Compose 扩展
- **THEN** 不隐式启动 Embedding、Qdrant、Knowledge MCP 或后台采集

### Requirement: ONES受管同步必须保持当前创建日窗口及原子切版
系统 SHALL 通过显式配置和启用的绑定执行首次历史全量和后续每 3600 秒最近七个北京时间创建日的采集、候选、分块、索引及受管激活。同步 MUST 只对同平台内容库和绑定明确钉住的合法已发布资源自动换版；管理员草稿、停用、连接、模型或发布修订变化 MUST 阻止激活。单来源活动 run SHALL 可恢复且互斥，内容、发布指针和水位 SHALL 在同平台短事务内原子切换；失败保留旧可用版本，不从缺项推断来源删除。

#### Scenario: 较早创建的事项最近更新
- **WHEN** 工作项创建日在最近七日之外但最近发生更新
- **THEN** 当前后续同步不声称覆盖该更新；扩大补扫范围须另行确定规格和 Provider 合同

#### Scenario: 激活前发布事实变化
- **WHEN** 已钉住资源存在管理员草稿、被停用或发布配置已改变
- **THEN** 同步拒绝激活并保留旧可用内容和资源版本

#### Scenario: 外部内容连接
- **WHEN** 在线知识资源使用独立内容 PostgreSQL
- **THEN** 其读取可按当前合同验证，受管同步不得自动向该外部库写入或切版
