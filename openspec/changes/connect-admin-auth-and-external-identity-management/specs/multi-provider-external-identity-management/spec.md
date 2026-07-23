## ADDED Requirements

### Requirement: 外部身份Connection定义受信Provider实例
系统 SHALL 持久化外部身份Connection的稳定编码、Provider、tenant/instance、验证模式、状态和受控连接引用，并 MUST 区分DingTalk Channel Connector与ONES业务系统Connection。

#### Scenario: 注册钉钉Connection
- **WHEN** 管理员选择启用且允许ingress的钉钉企业Stream Connector
- **THEN** 系统创建或读取引用该Connector的DingTalk身份Connection
- **AND** 不复制AppSecret或Stream凭据

#### Scenario: 注册ONES Connection
- **WHEN** 有Connection管理权限的管理员提交受支持ONES Provider、唯一实例编码和通过allowlist校验的Base URL
- **THEN** 系统保存非敏感Connection配置与revision
- **AND** 不允许配置任意登录Path、Method、Header或请求模板

#### Scenario: 禁用Connection
- **WHEN** 管理员禁用一个Connection
- **THEN** 该Connection下的身份不能用于新的解析或验证
- **AND** 已有Identity、Claim和审计历史保持不变

### Requirement: 一个内部自然人可以关联多个Provider身份
系统 SHALL 允许同一启用自然人关联多个钉钉企业、ONES实例和未来Provider身份，并 MUST 禁止服务账号绑定个人外部身份。

#### Scenario: 用户同时关联钉钉和ONES
- **WHEN** 同一内部用户拥有已验证钉钉身份和已验证ONES身份
- **THEN** 两个外部身份都指向同一个内部用户ID
- **AND** 各自保留独立Provider、Connection、subject、状态和用途

#### Scenario: 用户关联两个ONES实例
- **WHEN** 用户分别验证两个不同Connection上的ONES账号
- **THEN** 系统创建两个独立身份映射
- **AND** 不因外部UUID文本相同而跨实例合并

#### Scenario: 服务账号尝试绑定
- **WHEN** 管理员或服务账号尝试为`account_type=service`创建外部身份或Claim
- **THEN** 系统拒绝操作并记录安全审计

### Requirement: 外部主体在受信范围内唯一绑定
系统 MUST 使用Provider、tenant/Connection范围和external subject ID唯一识别外部身份，MUST NOT依据姓名、昵称、邮箱或手机号自动关联。

#### Scenario: 唯一外部主体首次绑定
- **WHEN** 验证结果中的subject在该Provider和Connection范围内尚未绑定
- **THEN** 系统原子创建指向目标内部用户的身份

#### Scenario: 相同主体绑定同一用户
- **WHEN** 同一用户再次验证已经属于自己的外部主体
- **THEN** 系统幂等刷新验证时间和受控Provider上下文
- **AND** 不创建重复身份

#### Scenario: 相同主体属于另一个用户
- **WHEN** 验证结果中的subject已经绑定其它内部用户
- **THEN** 系统保留原身份并把当前Claim标记为conflict
- **AND** 不自动覆盖、合并或转移身份

### Requirement: 身份可用状态和验证状态分别治理
系统 SHALL 分别维护管理员enabled/disabled状态与pending/verified/conflict/revoked验证状态，只有启用用户、启用Connection、启用Identity和verified状态同时满足时身份才可信。

#### Scenario: pending身份
- **WHEN** 管理员只创建尚未完成Provider证明的关联Claim
- **THEN** 页面显示pending且系统不把它用于Channel或业务主体解析

#### Scenario: verified身份被禁用
- **WHEN** 管理员禁用一个verified身份
- **THEN** 该身份停止解析新请求
- **AND** 其它身份、内部用户和历史记录不受影响

#### Scenario: Connection重新启用
- **WHEN** 管理员重新启用Connection但Identity本身仍disabled
- **THEN** 该身份继续不可用直到显式启用

### Requirement: Claim承载待验证和冲突流程
系统 SHALL 使用带revision的Claim记录pending、verified、conflict、rejected、expired和cancelled流程，并 MUST 保留验证与冲突治理的安全历史。

#### Scenario: 管理员创建待验证Claim
- **WHEN** 管理员为启用自然人选择受信Connection并创建Claim
- **THEN** 系统保存pending Claim及创建人
- **AND** 不要求或保存外部系统密码

#### Scenario: 用户完成自己的Claim
- **WHEN** 当前登录用户对属于自己的pending Claim完成Provider验证
- **THEN** 系统事务创建或刷新Identity并把Claim标记为verified

#### Scenario: 管理员查看冲突
- **WHEN** Claim进入conflict
- **THEN** 有冲突治理权限的管理员能看到当前绑定和Claim的安全摘要
- **AND** 看不到验证密码、Provider Token或原始响应

#### Scenario: 并发处理Claim
- **WHEN** 两个操作者基于相同旧revision处理Claim
- **THEN** 系统只接受第一个更新并向第二个返回409

### Requirement: 冲突处理不得一键强制转移身份
系统 SHALL 允许管理员保留现有绑定、拒绝或取消冲突Claim，并 MUST 要求身份转移经过显式停用旧绑定和目标用户重新验证的多步流程。

#### Scenario: 保留现有绑定
- **WHEN** 管理员确认现有内部用户归属正确
- **THEN** 系统拒绝冲突Claim并保留原Identity

#### Scenario: 需要转移归属
- **WHEN** 管理员判断原Identity归属错误
- **THEN** 系统要求先使用expected revision撤销旧Identity，再让目标用户重新验证
- **AND** 不提供绕过唯一约束的强制覆盖命令

### Requirement: 现有钉钉绑定平滑迁移到通用模型
系统 SHALL 为既有启用钉钉Connector建立Connection，并 MUST 将现有钉钉身份标记为verified/admin_asserted而不改变其内部用户、tenant、subject、connector和enabled状态。

#### Scenario: 迁移既有钉钉用户
- **WHEN** 迁移发现可唯一对应启用Connector的现有钉钉身份
- **THEN** 系统关联Connection并保留当前解析语义

#### Scenario: 现有身份无法找到Connector
- **WHEN** 迁移无法唯一确定可信Connection
- **THEN** 系统不伪造verified映射并生成待人工处理报告
- **AND** 不把该身份错误关联到其它tenant

### Requirement: 身份管理API与Web使用真实数据和细粒度权限
系统 SHALL 提供Connection、Provider、用户Identity、Claim、Conflict以及个人Identity的管理API和页面，并 MUST 根据用户自身或identity管理权限限制范围。

#### Scenario: 管理员查看用户详情
- **WHEN** 有用户与身份管理权限的管理员查看内部用户
- **THEN** 页面显示角色摘要、Identity、Claim、验证方法、最近验证时间、团队/租户上下文和状态
- **AND** 不显示Secret或完整Provider响应

#### Scenario: 用户查看自己的身份
- **WHEN** 普通用户进入“我的外部身份”
- **THEN** 页面只返回当前用户的Identity与Claim
- **AND** 用户不能通过修改路径或请求体读取其它用户

#### Scenario: 前端发生revision冲突
- **WHEN** Identity、Claim或Connection写请求返回409
- **THEN** 页面要求刷新并展示数据已变化
- **AND** 不静默覆盖服务器状态

### Requirement: 身份关联不授予额外业务权限
系统 MUST 把外部身份映射仅作为可信主体解析，MUST NOT因为成功关联钉钉、ONES或其它Provider而自动创建角色、平台数据范围、Business Application或API Capability权限。

#### Scenario: ONES身份验证成功
- **WHEN** 用户成功关联ONES账号
- **THEN** 用户的内部角色和平台权限保持原样
- **AND** ONES原生项目权限仍由ONES或未来API平台判断

#### Scenario: 群聊成员身份不同
- **WHEN** 同一钉钉群中的两名发送人关联不同内部用户和ONES身份
- **THEN** 系统按每条消息的发送人解析主体
- **AND** 不创建群级共享ONES身份或权限

### Requirement: 外部身份管理不得暴露凭据和敏感载荷
系统 MUST 在数据库、API、页面、日志和审计中排除密码、Session Token、CSRF值、Provider Token、AppSecret、完整Webhook URL和原始外部响应。

#### Scenario: 查看身份与验证历史
- **WHEN** 用户或管理员查看Identity、Claim或Verification Attempt
- **THEN** 系统只返回Provider、Connection、subject、受控上下文、状态、方法和时间
- **AND** 不返回任何可重放的认证材料
