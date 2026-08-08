## ADDED Requirements

### Requirement: 管理Web连接现有服务端Session认证
系统 SHALL 提供真实登录页并使用现有登录和当前用户API建立管理端认证状态，MUST 通过HttpOnly Cookie承载Session且不得在Local Storage、Session Storage、URL或前端持久化状态保存Session Token。

#### Scenario: 正确账号登录
- **WHEN** 启用的内部自然人提交正确用户名和密码
- **THEN** 后端创建服务端Session并设置安全Cookie
- **AND** 前端加载当前用户、角色和能力后进入原目标管理页面

#### Scenario: 登录失败
- **WHEN** 用户提交未知用户名、错误密码、停用账号或服务账号凭据
- **THEN** 页面显示统一登录失败信息
- **AND** 不泄露账号是否存在、具体失败字段或服务端异常

#### Scenario: 浏览器重新打开已有会话
- **WHEN** 浏览器携带有效Session Cookie重新加载管理Web
- **THEN** 前端通过`/api/auth/me`恢复用户和权限
- **AND** 不要求用户重复登录或从浏览器存储恢复Token

### Requirement: 未认证和已认证路由被明确隔离
系统 SHALL 使用认证路由保护管理页面，并 MUST 在认证状态尚未确定时阻止受保护页面读取和短暂显示管理数据。

#### Scenario: 未登录访问受保护页面
- **WHEN** 浏览器没有有效Session访问用户或外部身份页面
- **THEN** 前端跳转登录页并保留安全的站内return path
- **AND** 后端API返回未认证错误

#### Scenario: 恶意外部return path
- **WHEN** 登录页收到绝对URL、协议相对URL或其它站外return path
- **THEN** 系统忽略该值并在登录成功后进入默认站内页面

#### Scenario: 已登录访问登录页
- **WHEN** 已认证用户访问`/login`
- **THEN** 前端将其送回有权访问的默认管理页面

### Requirement: 前端API Client统一处理Cookie和CSRF
系统 SHALL 为所有管理端请求使用同源`credentials: include`，并 MUST 为状态变更请求从受控CSRF Cookie读取值并发送`X-CSRF-Token`。

#### Scenario: 合法写请求
- **WHEN** 已登录页面发送带允许Origin和有效CSRF的修改请求
- **THEN** 后端继续执行RBAC、revision和业务校验

#### Scenario: 缺少CSRF
- **WHEN** Cookie认证的写请求没有有效CSRF Header
- **THEN** API拒绝请求且前端展示安全错误
- **AND** 不把请求自动降级为无CSRF重试

#### Scenario: 服务端使用自定义Cookie名称
- **WHEN** 部署配置修改CSRF Cookie名称
- **THEN** 前端从安全公开认证配置读取名称
- **AND** 不需要修改每个业务模块或暴露Session Token

### Requirement: Session失效在整个管理Web一致处理
系统 SHALL 在Session过期、撤销、用户停用或密码修改后使所有受保护查询失效，并 MUST 将用户返回未认证状态。

#### Scenario: API返回401
- **WHEN** 任一受保护查询因为Session过期返回401
- **THEN** 前端清理认证Query缓存并进入登录页
- **AND** 不继续展示过期用户和敏感页面数据

#### Scenario: API返回403
- **WHEN** Session有效但用户没有目标资源权限
- **THEN** 前端保持登录状态并展示无权限页面
- **AND** 不把403误判为Session失效

### Requirement: 用户可以安全退出修改密码和管理自己的Session
系统 SHALL 连接退出、修改密码、Session列表和撤销接口，并 MUST 在这些操作后同步更新认证状态。

#### Scenario: 用户退出
- **WHEN** 用户确认退出
- **THEN** 系统撤销当前Session、清除Cookie和前端用户缓存并返回登录页

#### Scenario: 用户修改密码
- **WHEN** 用户提交正确当前密码和合规新密码
- **THEN** 后端更新密码并撤销该用户全部Session
- **AND** 前端清空密码字段并要求重新登录

#### Scenario: 用户撤销其它Session
- **WHEN** 用户在安全设置中撤销属于自己的其它Session
- **THEN** 系统将目标Session标记为撤销并刷新Session列表
- **AND** 用户不能查看完整Token或撤销他人Session

### Requirement: 导航展示与后端能力保持一致
系统 SHALL 根据当前用户能力展示用户、外部身份、Connection和其它管理入口，但 MUST NOT 把前端隐藏导航作为授权机制。

#### Scenario: 身份管理员登录
- **WHEN** 用户具有identity管理权限但没有其它平台管理权限
- **THEN** 前端显示允许的用户与外部身份入口并隐藏无权限命令
- **AND** 后端仍对每个请求执行对象级RBAC

#### Scenario: 普通用户登录
- **WHEN** 用户只有自己的安全设置和外部身份自助验证权限
- **THEN** 前端只显示个人安全与“我的外部身份”
- **AND** 不显示其它用户、Connection和冲突治理数据

### Requirement: 认证页面满足安全可用性要求
系统 SHALL 为登录、Session恢复、无权限、过期、限流和后端不可用提供明确状态，并 MUST 满足桌面、窄屏、键盘和辅助技术使用要求。

#### Scenario: 登录请求处理中
- **WHEN** 登录请求尚未完成
- **THEN** 页面禁用重复提交并提供可识别的忙碌状态
- **AND** 密码不出现在页面日志、URL、Toast详情或错误遥测中

#### Scenario: 键盘完成登录
- **WHEN** 用户只使用键盘或辅助技术完成登录
- **THEN** 用户名、密码、错误摘要和提交按钮具有正确标签与焦点顺序
- **AND** 错误状态不只依赖颜色表达
