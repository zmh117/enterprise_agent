## ADDED Requirements

### Requirement: Oracle 草稿技术验证必须委派给具备客户端的服务
管理端 SHALL 在校验管理员权限后把指定 Oracle 草稿委派给 tool-mcp 进行真实只读技术测试；API、Worker、Agent Runtime MUST NOT 为该流程安装 Instant Client，入口 MUST NOT 注册为 Agent 工具。只有匹配当前草稿的真实 PASSED 结果才能支持发布。

#### Scenario: 真实连接通过
- **WHEN** tool-mcp 的匹配架构 19c Thick 客户端连接 Oracle 11.2.0.4 并完成现有权限、字符集及只读探针检查
- **THEN** API 保存匹配该草稿的 PASSED 验证事实，管理员可按原发布流程发布

#### Scenario: 验证期间草稿或身份变化
- **WHEN** 请求所绑定草稿不再匹配当前版本/hash，或资源身份被停用
- **THEN** 系统拒绝使用该验证结果，不得使旧草稿或已停用身份获得可发布资格

### Requirement: Oracle 验证委派必须受鉴权且不得传输明文凭据
委派请求 SHALL 具备独立用途、限时签名和请求绑定，接收端 SHALL 重新验证操作人管理权限及资源/草稿身份。请求与响应 MUST 有大小、时间及并发限制；响应 MUST 绑定原请求并验证真实性。请求 MUST NOT 接受任意连接配置、SQL、密码或调用方指定的环境权限豁免。

#### Scenario: 未签名、过期、篡改、重放或跨资源请求
- **WHEN** 请求不满足委派约束
- **THEN** 接收端在解析密码和调用 Oracle 前拒绝请求；同进程已消费票据不能重复执行

#### Scenario: 管理服务不可用或返回异常载荷
- **WHEN** 目标不在部署允许的主机内，或请求超时、重定向、响应签名/关联不匹配
- **THEN** 技术测试失败关闭，不创建可发布验证结果，不尝试访问重定向目标

### Requirement: Oracle 技术测试必须返回可操作的安全失败类别
Oracle 验证 SHALL 区分客户端不可用、网络连接、认证、Service Name/SID、服务器版本、字符集、只读权限和未知探针错误，返回固定中文说明和安全代码，不得泄露驱动原始异常、凭据或业务数据。现有非本地只读策略 MUST 保留。

#### Scenario: 客户端不可用
- **WHEN** tool-mcp 没有合规客户端、客户端架构不匹配或 Thick 初始化失败
- **THEN** 返回客户端类 BLOCKED，明确尚未成功连接，不伪报账号权限错误

#### Scenario: 数据库认证或服务名失败
- **WHEN** Oracle 返回可识别的认证、锁定、过期、服务名或 SID 错误
- **THEN** 返回对应 FAILED 类别及安全错误码，不返回原始连接信息

#### Scenario: 只有替身测试通过
- **WHEN** 本地只执行单元或进程内 HTTP 测试而未连接真实 Oracle
- **THEN** 验收记录必须明确真实 Oracle 未验收，不得以此为任何真实资源发布依据
