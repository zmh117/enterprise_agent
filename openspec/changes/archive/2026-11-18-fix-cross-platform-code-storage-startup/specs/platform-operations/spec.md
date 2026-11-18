## MODIFIED Requirements

### Requirement: WSL2 和 Linux 部署必须核验控制器路径与首次初始化
部署 SHALL 支持 Windows 10/11 Docker Desktop 的 WSL2 Linux 容器操作方式及 Linux x86-64 虚拟机。知识控制器 MUST 使用固定容器路径只读挂载主部署目录与所需文件型 Secret，通过自身容器的项目标签、服务标签和只读挂载元数据确定 daemon 源路径；不得把宿主 Windows 盘符或 WSL 客户端别名直接作为嵌套 Compose 的挂载源。除下述受控源码目录初始化外，缺失宿主路径 MUST NOT 隐式创建为目录。控制器状态查询失败或路径不符时健康检查 MUST 失败，不能只凭进程心跳标为就绪。

部署 SHALL 提供不输出凭据或解析配置的兼容预检、显式全新安装卷初始化和启动后验收入口。卷初始化 MUST 先检查全部目标；已有项目容器、平台数据卷或未经该初始化入口标记的既有知识卷存在时拒绝，不删除或覆盖数据。普通启动和预检不得自动补建缺失知识外部卷。密钥初始化 SHALL 幂等补齐 Master Key 及现有角色身份材料。

Docker 文件型 Secret 初始化 MAY 显式对宿主源文件添加实际消费者固定 UID 的只读 POSIX ACL，目录 MUST 保持 owner-only，不得开放其他用户读取或放宽容器用户。继承 `python-deps` 的服务入口 SHALL 在应用启动前复制到运行用户所有、权限 `0400` 的私有 tmpfs 文件；普通非容器源文件继续保持 owner-only。不支持 ACL 或另有 UID 映射的环境 MUST 明确拒绝或另行验收，不把当前固定 UID 合同直接套用。

#### Scenario: Docker Desktop 使用不同的客户端与 daemon 路径
- **WHEN** 源码和 Secret 的 daemon 挂载源与控制器内可见路径不同
- **THEN** 控制器通过固定挂载点读取主文件及同一 `.env`，通过经验证的 daemon 源路径挂载知识服务 Secret，以容器内源码路径构建镜像
- **AND** 检查只处理挂载和标签元数据，不读取或输出凭据内容

#### Scenario: 全新安装重复执行卷初始化
- **WHEN** 项目尚无容器和平台数据，仅存在该初始化入口为同一项目创建的部分或全部知识卷
- **THEN** 只创建缺失知识卷，保留已有卷，最终验证四卷存在

#### Scenario: 错误项目名或卷名指向既有部署
- **WHEN** 初始化发现既有项目容器、平台数据或未标记知识卷
- **THEN** 在创建任何卷前拒绝并要求按升级流程核对，不自动以空库替代

#### Scenario: 目标环境验收边界
- **WHEN** 兼容预检、合成测试或模拟架构容器通过
- **THEN** 仅记录已检查的平台和范围，不宣称 Windows 或 x86 VM 整套部署已验收
- **AND** 启动后验收核对默认服务健康、一次性初始化退出码和真实控制器配置，业务授权、同步、检索及网页启停仍在各目标环境单独验收

#### Scenario: Windows 原生终端凭据路径
- **WHEN** CMD 或 PowerShell 未设置 HOME
- **THEN** 文件型 Secret 使用单文件显式路径，其次 PLATFORM_SECRETS_DIR，其次 USERPROFILE 下的 .config/enterprise-agent；Linux/macOS 仍默认 HOME，缺少所有来源时明确失败，不创建或替换密钥

### Requirement: SVN 必须支持三平台统一挂载与执行
部署 SHALL 支持 Windows Docker Desktop/WSL2、macOS Docker Desktop、Linux Docker Engine 的 Linux 容器；SVN CLI 仅由执行器调用，不依赖宿主原生 SVN。相同 CODE_SVN_CHECKOUT_HOST_ROOT SHALL 可写挂给 knowledge-sync、只读挂给 Runtime A/B，固定容器路径为 /var/lib/code-svn/checkout。宿主路径只经 Compose 长格式 bind 映射并核实 daemon Mounts.Source；不硬编码盘符、用户名、网络或路径别名，仅声明的源码与状态目录允许通过受控初始化自动创建；Secret 和其他宿主路径不得隐式误建。新流程不再依赖额外源码根挂载，凭据隔离沿用既有合同。

#### Scenario: 更新后读取同一目录
- **WHEN** knowledge-sync 在无读者时完成一次合法 update
- **THEN** 后续获准的 Runtime 从同一只读挂载看到新版本，无需复制快照或重新构建镜像

#### Scenario: 三平台验收
- **WHEN** 宣称可以跨平台部署
- **THEN** 分别提供真实 CLI、中文/空格路径、A/B 拒写、同版本并发读、读写/写写互斥及异常恢复证据，注明架构；不能用 Mac 单平台测试代替其他环境

### Requirement: 代码知识部署必须显式初始化并预检目录和启用状态
部署 SHALL 在主 Compose 中提供无网络、无凭据的一次性目录初始化。源码与 SVN 状态目录的 bind SHALL 支持创建缺失目录，API、Runtime A/B、knowledge-sync 和控制器 MUST 等待初始化成功后启动。初始化 SHALL 验证全部固定目标为非链接目录且根不重叠，仅设置源码根和状态根、configuration、client、trusted-ca 五个目录的所有权和模式；MUST NOT 递归修改既有工作副本、读取或替换凭据文件。初始化 SHALL 用临时合成文件验证执行器可写与 Runtime 组可读，失败阻断消费者启动。预检 MUST 保持只读，检查初始化依赖、目录存在、挂载与组一致性；要求代码能力时 MUST 拒绝未启用的执行器。配置示例 SHALL 显式记录开关与目录参数。手动严格初始化入口可继续用于维护，凭据文件与知识外部卷不在自动初始化范围。

#### Scenario: 全新目录直接启动
- **WHEN** Windows CMD/PowerShell、macOS 或 Linux 的源码与状态目录缺失，执行主 Compose up
- **THEN** 创建配置指定的目录，初始化成功后启动消费者，不因不存在的源码 bind 中断

#### Scenario: 初始化保留旧数据
- **WHEN** 固定目录已有工作副本或状态材料
- **THEN** 仅检查和设置固定根目录元数据，已有子文件内容、权限和身份保持不变，不递归修复

#### Scenario: 初始化失败
- **WHEN** 固定目录是符号链接、根重叠、或真实身份访问探测失败
- **THEN** 返回固定错误码，依赖服务不得开始运行，不输出源代码或凭据

#### Scenario: 代码执行器关闭
- **WHEN** 部署要求代码查询但 CODE_CHECKOUT_ENABLED 未启用
- **THEN** 预检失败；未要求代码查询时检查结果明确列出关闭状态
