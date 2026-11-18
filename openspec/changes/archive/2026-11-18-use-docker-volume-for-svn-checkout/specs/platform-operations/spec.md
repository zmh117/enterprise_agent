## MODIFIED Requirements

### Requirement: 受管检出目录必须直接只读提供给 Runtime
系统 SHALL 支持从现有已完成检出任务登记受管工作副本，绑定 source、仓库 UUID、分支、已选目录/文件范围和当前 revision。knowledge-sync 可写该工作副本；Runtime A/B MUST 将同一 Docker 命名卷检出根映射到固定容器路径并只读使用，不另建源码快照、封存副本、按版本目录或独立提取任务。登记不触发模型、不接受任意宿主路径；同一真实工作副本不能通过别名或重叠登记获得多个锁身份。模型只能读 grant 范围内的受支持文件，不能访问 .svn、未跟踪项、未授权 externals 或越界链接。

#### Scenario: 直接使用已检出工程
- **WHEN** 管理员登记已完成的 set_server/EBR/JTH 受管检出
- **THEN** 两个 Runtime 从相同检出根只读访问获准子集，不生成第二份代码，不需要配置独立提取应用

#### Scenario: 部分工程与目录别名
- **WHEN** 只检出 EBR，或试图用重叠路径再次登记同一工作副本
- **THEN** 前者允许使用但明确缺失后端/JTH；后者拒绝，不得借两个登记身份绕过互斥

### Requirement: SVN 必须支持三平台统一挂载与执行
部署 SHALL 支持 Windows Docker Desktop/WSL2、macOS Docker Desktop、Linux Docker Engine 的 Linux 容器；SVN CLI 仅由执行器调用，不依赖宿主原生 SVN。同一个 Docker local 命名卷 SHALL 可写挂给 knowledge-sync、只读挂给 Runtime A/B，固定容器路径为 /var/lib/code-svn/checkout；CODE_SVN_CHECKOUT_VOLUME 可指定该卷实际名称，禁止 local driver_opts 将共享目录或网络盘包装成工作副本卷。控制器 SHALL 以 daemon Mounts.Name 和卷元数据核实并复用同一卷，不将卷 Mountpoint 转成 bind。SVN 状态/CA 等宿主路径仍经 Compose 长格式 bind 映射并核实 daemon Mounts.Source；不硬编码盘符、用户名、网络或路径别名，仅声明的源码与状态目录允许通过受控初始化自动创建；Secret 和其他宿主路径不得隐式误建。新流程不再依赖额外源码根挂载，凭据隔离沿用既有合同。

#### Scenario: 更新后读取同一目录
- **WHEN** knowledge-sync 在无读者时完成一次合法 update
- **THEN** 后续获准的 Runtime 从同一只读挂载看到新版本，无需复制快照或重新构建镜像

#### Scenario: 三平台验收
- **WHEN** 宣称可以跨平台部署
- **THEN** 分别提供真实 CLI、中文/空格路径、A/B 拒写、同版本并发读、读写/写写互斥及异常恢复证据，注明架构；不能用 Mac 单平台测试代替其他环境

#### Scenario: 由宿主检出根切换到命名卷
- **WHEN** 既有安装升级到命名卷
- **THEN** 保留旧宿主目录与数据库数据；维护窗口内停止旧使用者，初始化新卷并重建全部消费者，以新目录名重新检出并显式绑定，不自动复制或删除旧工作副本

#### Scenario: 网页启动复用源码卷
- **WHEN** 控制器通过网页重新创建 knowledge-sync
- **THEN** 从自身只读卷挂载取得已核实的实际卷名，新执行器与 Runtime 仍使用同一卷；类型、名称或卷驱动选项异常时失败，不退回旧宿主目录

### Requirement: 代码知识部署必须显式初始化并预检目录和启用状态
部署 SHALL 在主 Compose 中提供无网络、无凭据的一次性目录初始化。源码卷 SHALL 由 Compose 创建并挂载；SVN 状态目录的 bind SHALL 支持创建缺失目录，API、Runtime A/B、knowledge-sync 和控制器 MUST 等待初始化成功后启动。初始化 SHALL 验证全部固定目标为非链接目录且根不重叠，仅设置源码根和状态根、configuration、client、trusted-ca 五个目录的所有权和模式；MUST NOT 递归修改既有工作副本、读取或替换凭据文件。初始化 SHALL 用临时合成文件验证执行器可写与 Runtime 组可读，失败阻断消费者启动。预检 MUST 保持只读，检查初始化依赖、状态目录存在、命名卷元数据、挂载与组一致性；MUST NOT 从宿主文件系统读取 Docker 卷 Mountpoint；要求代码能力时 MUST 拒绝未启用的执行器。配置示例 SHALL 显式记录开关与目录参数。手动严格初始化入口可继续用于维护，凭据文件与知识外部卷不在自动初始化范围。

#### Scenario: 全新目录直接启动
- **WHEN** Windows CMD/PowerShell、macOS 或 Linux 的源码卷与状态目录缺失，执行主 Compose up
- **THEN** 创建配置指定的卷及状态目录，初始化成功后启动消费者，不因不存在的源码 bind 中断

#### Scenario: 初始化保留旧数据
- **WHEN** 固定目录已有工作副本或状态材料
- **THEN** 仅检查和设置固定根目录元数据，已有子文件内容、权限和身份保持不变，不递归修复

#### Scenario: 初始化失败
- **WHEN** 固定目录是符号链接、根重叠、或真实身份访问探测失败
- **THEN** 返回固定错误码，依赖服务不得开始运行，不输出源代码或凭据

#### Scenario: 代码执行器关闭
- **WHEN** 部署要求代码查询但 CODE_CHECKOUT_ENABLED 未启用
- **THEN** 预检失败；未要求代码查询时检查结果明确列出关闭状态
