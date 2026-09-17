## ADDED Requirements

### Requirement: 知识部署必须通过可选 Compose 扩展显式启用
系统 SHALL 将知识模型准备、Embedding、Qdrant、运维 CLI 及专用网络/卷定义放在 `knowledge/compose.yml`，通过显式叠加根 Compose 在同一项目启用。根 Compose MUST NOT 自动包含这些服务或知识网络。叠加 MUST 保留 PostgreSQL 既有网络、原模型/Qdrant 卷身份、无公开端口与运行隔离；数据库结构仍由共享 Migrator 管理，不按 Compose 开关跳过 schema 校验。

#### Scenario: 部署不需要知识库的环境
- **WHEN** 只加载根 Compose，包括启用其全部 profiles
- **THEN** 配置中不含知识服务、知识专用卷或网络，不要求知识服务的数据库配置，不下载模型或启动向量服务

#### Scenario: 现有环境显式启用知识库
- **WHEN** 按根文件在前的顺序叠加知识 Compose，并提供同库内部 DATABASE_DSN
- **THEN** 保持项目和模型/Qdrant 卷身份，仅为 PostgreSQL 追加知识网络，不另建数据库实例或向准备/推理服务传递数据库凭据

### Requirement: 本地知识向量化必须隔离模型准备与真实数据推理
系统 MUST 将公开模型文件准备与持有知识文本的运行服务隔离。准备任务 MUST NOT 获得知识数据库凭据或正文；推理服务 MUST 使用固定版本的本地模型文件、关闭远程代码及外网回退，并在文件缺失时拒绝就绪。首版 Embedding 与 Qdrant SHALL 仅在 Docker internal 网络可达，不发布宿主机端口；日志和参数错误 MUST NOT 包含真实文本、查询、向量或敏感连接内容。

#### Scenario: 权重尚未准备
- **WHEN** 本地固定版本模型文件不完整
- **THEN** 推理服务就绪失败，不下载临时替代版本、不调用云端推理

#### Scenario: 加载官方 PyTorch 权重
- **WHEN** 使用固定版本的官方 pytorch_model.bin
- **THEN** 系统先校验固定文件摘要，再显式 weights_only=True 受限加载，不添加任意类 allowlist 或回退不受限反序列化，不要求额外转换格式

#### Scenario: 处理真实文本
- **WHEN** 执行向量化或检索查询
- **THEN** 请求只到固定内部端点，不跟随重定向或环境代理，推理服务不能访问公网

#### Scenario: 用户误填请求
- **WHEN** 输入形状或长度不合法
- **THEN** 返回不包含输入内容的固定错误码，不把框架原始校验异常写入输出

### Requirement: 知识 Embedding 必须有界且绑定一致的向量配置
系统 SHALL 使用固定的 BGE-M3 dense 配置生成 1024 维归一化向量，并在索引配置中记录模型完整版本、tokenizer/运行配置、维度、距离及文本规则摘要。文档与查询 MUST 使用相同向量空间。首版单条最多 4096 tokens、每批最多 8 条且合计最多 8192 tokens，MUST 真实分词计数且不得静默截断。结果 MUST 校验数量、顺序、维数、有限值及非零向量；服务 MUST 有并发、请求体、超时及重试上限。

#### Scenario: 字符预算内但 token 超限
- **WHEN** 某个已分块文本仍超过模型服务 token 限额
- **THEN** 预检报告超限并停止该项，不截掉证据尾部继续索引

#### Scenario: 模型或向量配置变化
- **WHEN** 文档索引与查询服务指纹不同，或现有 collection 维数/距离不匹配
- **THEN** 系统拒绝读写，不混用空间；新配置需要新的索引版本

### Requirement: 知识向量索引必须具有独立清单和可恢复检查点
系统 MUST 在 knowledge.vector_index 和 knowledge.vector_index_item 保存明确语料快照、完整配置及逐块状态，由正式 Migrator 管理双引擎 DDL、约束、中文注释和事实源。原来源/分块九表 MUST NOT 因建立向量索引而修改；PostgreSQL 不重复存储向量。清单绑定知识库、当前版本、块身份及文本摘要，新语料或新配置 MUST 新建索引版本。

#### Scenario: 构造索引清单中断
- **WHEN** 输入清单尚未补齐或预期数量/摘要未通过检查
- **THEN** 索引保持非 READY，重跑只在同一固定输入下补齐，不提前执行不完整集合的就绪发布

#### Scenario: 新缺陷或新版本到来
- **WHEN** 原语料快照与当前有效收录不一致
- **THEN** 不静默扩充或覆盖原索引，要求明确创建新索引版本；旧数据保留可追溯性

### Requirement: PostgreSQL 和 Qdrant 之间必须通过稳定身份恢复一致性
每个索引块 MUST 使用确定 point ID。系统 SHALL 以 Qdrant 确认写入后记录 PostgreSQL 检查点，网络调用 MUST NOT 置于数据库行级事务中。重跑 MUST 逐项核验预期点及身份，缺失点可补写，不匹配点必须停止；不能只凭检查点或集合总数推断成功。Qdrant payload MUST 只包含最小标识及摘要，不包含正文。CLI MUST 默认预检、显式提交，且同索引只有一个写者。

#### Scenario: Qdrant 写入后进程中断
- **WHEN** 点已写入但 PostgreSQL 未记录成功
- **THEN** 重跑核对确定点身份并补记或安全补写，不新增重复点

#### Scenario: 既有点消失或身份冲突
- **WHEN** PostgreSQL 检查点与 Qdrant 实际点不一致
- **THEN** 缺失点可恢复，冲突身份不得自动覆盖，索引不能被标记为完整 READY

#### Scenario: 完整集合就绪
- **WHEN** 全部预期点身份、配置、数量和当前来源状态通过核验
- **THEN** 索引才成为 READY，重复执行不新增点或修改来源数据

### Requirement: 本地知识检索必须回源校验且不产生业务授权
本轮检索 SHALL 仅提供本机运维 CLI，指定 READY 索引与知识库，默认 top_k=10、最大20，并在最多200候选内回 PostgreSQL 校验当前版本、active 文档、included 收录及摘要。系统 MUST 按文档去重、保留证据定位；过滤或去重造成不足时 SHALL 明确 partial 状态，不能声称完整结果。CLI 输出只含安全引用/分数/标记，不打印真实正文或查询。不发布 Agent/MCP/Web 权限，storage_only 与 offline_unverified MUST 保持原有语义。

#### Scenario: 检索期间文档版本或收录失效
- **WHEN** Qdrant 命中旧版本或已移出的文档
- **THEN** 该候选不返回，不将存在向量当作当前有效性或读取授权

#### Scenario: 多块集中命中同一文档
- **WHEN** 多个候选属于同一缺陷
- **THEN** 返回按文档合并的结果及有界证据引用，不让重复块冒充多个缺陷

### Requirement: 本地向量索引验收必须区分计算链路和业务召回效果
上线全量前 MUST 验证镜像架构、模型版本、网络隔离及有界小样本基准。正式验收 SHALL 对执行时核实的全部块验证点集合、来源未变、幂等重放、失败恢复和服务重启持久性，报告真实耗时/内存而非推测。合成样例和原文自查询 MUST NOT 被称为真实业务 Recall@K；未提供人工标注集时必须注明业务召回效果未验证。

#### Scenario: 小批次超限或内存不足
- **WHEN** 基准出现超长输入、模型不兼容、超时或 OOM
- **THEN** 停止扩大运行并报告安全诊断，不自动换模型、接云端或裁剪证据

#### Scenario: 只有合成测试和原文自查询结果
- **WHEN** 尚无人工标注业务查询集
- **THEN** 可以报告链路与索引正确性，不声称召回率达到阈值或已提高业务检索质量
