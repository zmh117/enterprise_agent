## ADDED Requirements

### Requirement: 业务代码提取 Skill 必须输出有证据的候选知识
系统 SHALL 提供代码受管 `extract-business-knowledge` Skill，指导受管 Python Agent 在固定来源快照和允许范围内定位入口、读取相关实现、追踪依赖并输出标准候选包。Skill MUST 区分后端、工厂端前端、集团端前端的事实，保留状态原值、guard 逻辑、配置、检查时点、事务/异步边界、代码证据与未知项；不得只按关键词、提交说明或固定模板生成业务结论。输出 SHALL 包含 manifest、knowledge、evidence、relations、coverage、changes 及人读报告。Skill MUST NOT 授予 SVN/Shell/数据库写入或快照激活权限，也不得声称结构校验即业务正确性验证。

#### Scenario: 首次提取当前本地代码
- **WHEN** Job 固定的来源为未映射 SVN 的 local_bundle
- **THEN** 输出绑定该本地基线的候选知识和来源限制，不虚构 SVN revision

#### Scenario: 检测到配置例外
- **WHEN** 实现允许在特定配置下选择未发布处方
- **THEN** 保留配置条件和实际适用对象，不概括成“所有处方必须已发布”或把规则外推到主配方

#### Scenario: 依赖没有读到
- **WHEN** 公共实现不可访问或条件编译无法确定
- **THEN** 输出未解析依赖和受影响结论，不用注释、常识或模板补成确定事实

### Requirement: 业务知识问答 Skill 必须补齐版本与业务端上下文
系统 SHALL 提供 `code-business-query` Skill，指导 Agent 先发现获准代码 KB，再解析用户明确的 SVN revision、本地基线、latest_verified 或可信部署/会话版本。缺少必要版本或业务对象歧义时 MUST 请求澄清；已明确的上下文可以复用但必须核实并在答案中显示。指定版本未就绪时 SHALL 展示构建状态或不可用事实，不擅自选择最近版本。Skill SHALL 区分工厂端 EBR、集团端 JTH 和共同后端，以及 MES 集团授权与本平台授权。

#### Scenario: 用户只问工单是否可以发布
- **WHEN** 不同版本可能存在不同规则且没有明确版本上下文
- **THEN** 提示用户提供 SVN revision 或明确选择当前本地基线，不默认使用开发最新规则

#### Scenario: 当前会话已明确 r100
- **WHEN** 用户继续询问同一来源范围内的规则且没有切换版本
- **THEN** 使用核实后的 r100 并标明版本，不重复询问已确定信息

#### Scenario: 用户指定 r100 而只有 r101 就绪
- **WHEN** 工具返回 r100 的构建状态
- **THEN** 告知 r100 尚未就绪，不能引用 r101 的规则并标成 r100

### Requirement: 业务知识回答必须使用完整规则与变化证据
问答 Skill SHALL 在搜索定位后读取完整操作及必要依赖，对“何时改变/两个版本有什么不同”调用结构化比较或历史工具。回答 MUST 保留来源版本、适用条件、证据位置、覆盖边界和未知项；向量分数不得当作可信度，未展开依赖不得当作不存在的限制。规则解释与具体现场原因必须区分，首期只列出需要核验的现场数据，不声称已查询真实业务记录。普通答案 MUST NOT 包含源码全文、真实凭据或原始业务消息。

#### Scenario: a 非空校验在 r101 取消
- **WHEN** 工具提供 r100/r101 的完整条件差异与证据
- **THEN** 解释该条件在 r101 不再阻止发布，并保留其他条件，不把一个条件放宽说成工单必然发布成功

#### Scenario: 历史追溯尚有未决区间
- **WHEN** 工具只确认 r100 到 r105 之间发生过变化
- **THEN** 回答该范围及未决事实，不捏造精确提交号或从提交说明推断首次变化时间

#### Scenario: 用户询问某张工单的根因
- **WHEN** 只有代码知识而没有对应时点的工单、配置和关联对象数据
- **THEN** 返回适用规则和待核验条件，不把静态规则直接认定为现场根因

### Requirement: 代码业务 Skill 必须显式进入新发布版本
两个 Skill SHALL 进入现有代码受管目录和发布校验，其内容版本/摘要 MUST 进入可追溯的提取或问答配置。Skill 的选择不得改变强制安全层、注册工具或当前数据授权；旧 Agent/Application Publication 和 Job MUST NOT 自动加载新增 Skill。提取 Skill 只有在受管提取任务及其来源读取合同满足时才可执行完整流程。

#### Scenario: 部署新增 Skill 文件
- **WHEN** 旧 Publication 尚未选择该 Skill
- **THEN** 旧 Job 的提示词和能力不变，管理员通过新发布显式启用

#### Scenario: 只选择 Skill 没有工具权限
- **WHEN** 普通 Agent 加载提取 Skill 但没有受管构建绑定
- **THEN** 不获得源码读取能力，也不能以 Skill 文本绕过服务端权限
