## ADDED Requirements

### Requirement: 受管源码挂载使用独立 Runtime 控制身份
系统 SHALL 复用 Service Principal 信任根与短 Token 机制，为代码提取提供可选固定角色 `code-knowledge-runtime`、独立 audience `code-knowledge-control` 和唯一 scope `internal:code-knowledge:source-grant`。该身份只允许访问元数据授权入口，MUST NOT 授予 File Service、知识查询、数据库权限或源码全文传输。入口 SHALL 按确切 Job/Invocation/request_digest 复核 RUNNING 状态、未撤销的 Runtime 与构建租约、固定 Publication/服务账号、当前应用业务权限和来源范围。Runtime SHALL 在每次源码或产物操作前复查；未启用部署配置、复查失败或绑定变化时拒绝操作。

#### Scenario: 当前服务账号被撤权
- **WHEN** 提取 Job 尚在运行，但账号被停用或失去应用业务角色
- **THEN** 下一次 Read/Glob/Grep/Write/Edit 或候选产物提交被拒绝，已挂载目录不构成授权依据

#### Scenario: 普通服务身份请求源码授权
- **WHEN** File Worker、Knowledge MCP 或普通用户 Token 调用源码授权入口
- **THEN** 因固定角色和 audience 不匹配而拒绝，不扩大现有服务身份权限

#### Scenario: 迟到执行使用旧授权
- **WHEN** 请求引用其他 Invocation、不同 request_digest、过期租约或已结束 Job
- **THEN** 授权入口拒绝，来源范围不能由请求自行指定

### Requirement: 历史缓存内部接口必须使用双身份与当前来源策略
知识 MCP SHALL 使用现有独立服务身份与当前 Job Business Principal 调用固定 `code-history` 内部接口。控制面 SHALL 复核所调用知识工具 scope、当前用户及应用知识库授权、冻结资源发布、Job 剩余预算及来源按需策略；只允许幂等登记该来源的精确 revision 和持久化由服务器重新计算的历史检查进度。接口 MUST 拒绝浏览器 Cookie/Origin、非固定 Host、任意命令、URL、宿主路径和调用者提交的业务判断。MCP 数据库角色保持 SELECT，不获得代码需求或检查事实的写权限。该接口不得读取源码、扩大来源或激活开发/现场版本。

#### Scenario: 查询冷版本但未启用按需策略
- **WHEN** 当前授权用户查询尚未构建的确切 revision，而来源未启用按需策略
- **THEN** 系统返回 BUILD_REQUIRED，不启动 SVN 采集或模型任务

#### Scenario: 已授权历史请求通过双身份进入控制面
- **WHEN** 双身份、当前发布和已启用策略均有效
- **THEN** 同一来源/配置/revision 复用同一需求，遵守待处理上限，返回持久需求状态而不改变开发或现场指针
