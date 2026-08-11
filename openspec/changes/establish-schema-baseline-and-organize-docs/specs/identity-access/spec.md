## ADDED Requirements

### Requirement: 空库必须幂等创建唯一初始管理员
初始管理员 bootstrap MUST 在 schema migration 成功后创建唯一启用的人类用户 `admin`、显示名称 `Administrator`、受保护的 `platform-admin` 角色和启用的成员关系；系统 MUST 只保存符合现有密码策略的 Argon2 密码哈希，并不得记录、返回或持久化明文密码。

#### Scenario: Local 空库创建初始管理员
- **WHEN** `APP_ENV` 为 local 或 test、数据库尚无管理员且 bootstrap 未提供外部密码文件
- **THEN** 系统创建 `admin` 并使密码 `111111111111` 可用于本地首次登录，同时数据库、日志和命令输出均不包含该明文

#### Scenario: 重复执行 Bootstrap
- **WHEN** 初始管理员、平台管理员角色或成员关系已经存在
- **THEN** bootstrap 幂等完成且不创建重复用户、重复角色或重复成员关系，不重置任何现有密码、状态或 revision

#### Scenario: 存在其他管理员
- **WHEN** 数据库已有至少一个有效平台管理员但不存在固定 ID 的本地管理员 fixture
- **THEN** bootstrap 保留现有管理员事实并安全退出，不额外创建默认管理员

### Requirement: 非本地环境不得使用固定初始密码
在 staging、production 或其他非 local/test 环境中，初始管理员 bootstrap MUST 从受控文件、容器 Secret 或交互式安全输入获得密码；缺少输入时 MUST 失败关闭，MUST NOT 回退到 `111111111111`、命令行参数、普通环境变量或仓库内明文。

#### Scenario: Production 空库提供密码文件
- **WHEN** production 空库通过权限受限的密码文件提供合规初始密码
- **THEN** 系统创建初始管理员、立即丢弃明文输入并只保存 Argon2 哈希

#### Scenario: Production 空库没有安全密码输入
- **WHEN** production 数据库没有管理员且 bootstrap 未获得受支持的安全密码输入
- **THEN** 初始化非零退出并阻止业务服务启动，错误不包含密码或其他 Secret
