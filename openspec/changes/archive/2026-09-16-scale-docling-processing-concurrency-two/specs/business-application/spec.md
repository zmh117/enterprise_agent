## ADDED Requirements

### Requirement: Profile hash更新不得阻断应用管理和重新发布
当代码发布的`docling-layout-ocr-v2`保持同一Profile code但完整payload与hash发生变化时，系统 MUST 保留旧Revision、Publication、Deployment、历史终态Job和processing run的不可变身份与只读可见性。旧hash不再是当前可激活Profile时，管理端列表、详情、编辑入口和创建新Revision MUST 继续可用；系统 SHALL 把旧Publication的文档处理组件标记为`CONFIGURED_UNAVAILABLE`并返回稳定的Profile过期原因，而不得把管理服务整体报告为不可用、把Application事实删除或原地改写旧hash。

#### Scenario: 更新代码后打开使用旧hash的应用
- **WHEN** 管理员打开仍引用旧`docling-layout-ocr-v2` hash的Business Application
- **THEN** 列表和详情返回原Application、Revision、Publication及只读旧hash状态
- **AND** 页面允许管理员进入组成配置并创建使用当前Profile的新Revision

#### Scenario: 从旧Publication创建新Revision
- **WHEN** 管理员基于旧Publication编辑且继续选择`docling-layout-ocr-v2`
- **THEN** 新Revision解析并冻结代码当前发布的完整Profile payload与hash
- **AND** 旧Revision、旧Publication、历史Job和历史终态run保持不变

#### Scenario: 尝试重新激活旧hash Publication
- **WHEN** 管理员尝试激活不再受当前代码支持的旧Profile hash Publication
- **THEN** 激活预检以稳定Profile过期原因拒绝
- **AND** 管理端继续允许查看旧Publication并发布当前Profile的新Revision

#### Scenario: 发布并激活当前hash
- **WHEN** 管理员完成当前Profile新Revision的校验、发布和显式激活
- **THEN** 后续新Job固定新Publication和新Profile hash
- **AND** 系统不自动改绑旧route、旧Job、旧run或旧Representation

### Requirement: Profile hash切换前必须排空旧hash非终态处理
部署切换预检 MUST 统计旧Profile hash关联的非终态parent run、picture item和仍可能存在的外部Docling task，并在计数非零或状态不可确定时失败关闭。只有旧hash文档处理工作已确定终态，系统才能启用新的双Worker双执行器拓扑；该排空规则不得把旧Revision、Publication、Deployment或历史终态事实当作需要删除或原地迁移的对象。

#### Scenario: 旧hash仍有运行中任务
- **WHEN** 部署预检发现旧hash存在`QUEUED`、`SUBMITTED`、`RUNNING`或`RETRY_WAIT`的parent或picture工作
- **THEN** 切换被阻止并只报告按状态聚合的安全计数
- **AND** 运维先让旧拓扑排空或按既有确定失败流程终结任务

#### Scenario: 只剩旧hash历史终态事实
- **WHEN** 旧hash仅被历史Revision、Publication、Deployment、终态Job、终态run或不可变Representation引用
- **THEN** 部署预检允许继续
- **AND** 系统保留这些事实供审计与既有Job读取，不要求数据库改写hash

#### Scenario: 切换后管理旧Publication
- **WHEN** 新拓扑已就绪但管理员尚未重新发布某个旧hash应用
- **THEN** 该应用仍可进入、查看和编辑，文档处理组件明确显示不可用及重新发布指引
- **AND** 其它不依赖旧Profile hash的管理能力不得因该组件状态失败
