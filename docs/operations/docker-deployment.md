# Windows WSL2 与 x86 Linux Docker 部署

所有服务仍只使用根 `docker-compose.yml` 启动。本手册覆盖 Windows 10/11 + Docker
Desktop（WSL2、Linux 容器）和 Linux x86-64 虚拟机；不覆盖 Windows 原生容器。
代码兼容、容器健康和真实业务验收分别记录，不能互相代替。

## 主机准备

| 项目 | Windows 10/11 | x86-64 Linux 虚拟机 |
| --- | --- | --- |
| Docker | Docker Desktop 启用 WSL2 和目标发行版的 WSL Integration，切换 Linux 容器 | Docker Engine 与 Compose plugin |
| 操作终端 | WSL2 Linux 终端，安装 Git、Python 3.10+、OpenSSL、acl | Linux shell，安装 Git、Python 3.10+、OpenSSL、acl |
| 仓库与密钥 | 建议分别位于 WSL 的 `~/enterprise_agent`、`~/.config/enterprise-agent` | 如 `/opt/enterprise_agent` 和部署账号的 `~/.config/enterprise-agent` |
| 架构 | `docker version --format '{{.Server.Os}}/{{.Server.Arch}}'` 应为 `linux/amd64` | 同左；x86 指 64 位，不支持 32 位容器 |
| Compose | 2.24.0 或更新版本；预检支持 Compose 5 的版本号 | 同左 |

Windows 在 WSL 内执行本页命令，不混用 PowerShell 的 `$env:`、`C:\...` 和 Linux
环境变量写法。推荐把仓库放在 WSL Linux 文件系统中，而非 `/mnt/c`；这是
[Docker 的 WSL 性能建议](https://docs.docker.com/desktop/features/wsl/best-practices/)。
PowerShell 可用来检查 `wsl --list --verbose`，确认目标发行版为版本 2。
不要为此另起一个与 Docker Desktop 不同的 daemon；预检和实际部署必须使用同一个 context。

需要为 Docker 分配足够 CPU、内存和磁盘。当前重排服务单独限制 6 CPU/3 GiB，后台
Embedding、在线 Embedding、Docling 和数据库还会占用资源，6 CPU/3 GiB 不是整套要求。
根据主 Compose 的各服务限额预留容量，首次模型下载和构建可能持续较久；检查下载来源可达，
不要把模型下载中误判为初始化卡死。操作系统和架构检查通过不代表容量压测通过。

## 全新安装

以下命令均在仓库根目录执行。只适用于没有既有业务数据的新安装。

1. 初始化文件材料。脚本生成 Runtime/Principal 密钥、角色 bootstrap token、Docling Key、
   Master Key，重复执行保留原值，拒绝空文件、符号链接和不完整密钥对。

   ```sh
   sh scripts/bootstrap_agent_runtime_secrets.sh "$HOME/.config/enterprise-agent" --docker-acl
   test -e .env || cp .env.example .env
   chmod 600 .env
   ```

   默认文件路径已经与脚本一致。自定义目录时，必须同时修改 `.env` 中所有对应 `*_FILE`
   宿主机路径。管理员初始化沿用[既有初始化流程](schema-baseline-bootstrap.md)。
   备份 Master Key；已有环境不能改用新目录生成另一份 Key。

   `--docker-acl` 用 Linux `setfacl` 只给该文件的固定容器消费者 UID 加读取 ACL，目录仍为
   `0700`，其他用户不增加权限。Compose 文件型 Secret 不会通过声明 `uid/gid/mode` 改变
   宿主文件所有权（见 [Compose Secret 文档](https://docs.docker.com/reference/compose-file/services/#secrets)），因此只设 `0400` 可能让非 root 容器无权读取。入口再复制到私有 tmpfs，
   副本固定为运行用户所有的 `0400`。此选项要求支持 POSIX ACL 的 Linux 文件系统；
   不支持时失败，勿改为 `chmod 644`。不带此选项仍保持普通 owner-only 初始化模式。
   宿主 rootless Docker 或 userns-remap 会改变 UID 映射，不在本次部署范围，应单独验证。

2. 编辑 `.env`。固定 `COMPOSE_PROJECT_NAME`，填写高强度 `DINGTALK_RUNTIME_AUTH_TOKEN`、
   `MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD`、`AGENT_RUNTIME_DATABASE_PASSWORD`，并保持
   `AGENT_RUNTIME_DATABASE_DSN` 中密码一致。真实部署设置正确的 `APP_ENV`、浏览器来源、HTTPS
   Cookie、ONES 地址及允许列表；仅本地离线知识测试显式设置 `KNOWLEDGE_ACCESS_MODE=offline`。
   模型、连接凭据和业务资源按现有管理流程配置，不在部署脚本中自动授权。

   发布用 `BUILD_SOURCE_REVISION`、`BUILD_ID` 也写入根 `.env`，API、Worker、Runtime、File
   Service 使用同一次发布的值。不要只在 shell 中临时 export 配置，否则网页控制器无法复现。

3. 显式初始化源码与状态目录，再准备知识外部卷。以下使用默认目录；自定义路径应与
   `.env` 中 `CODE_SVN_CHECKOUT_HOST_ROOT`、`CODE_SVN_LOCAL_STATE_ROOT` 完全一致：

   ```sh
   sudo python3 scripts/deployment_check.py init-code-directories \
     --checkout-root "$(pwd -P)/.local/code-svn/checkout" \
     --state-root "$(pwd -P)/.local/code-svn/state"
   ```

   初始化不读取 `.env` 或凭据，也不连接 Docker。源码根为 UID 10003、GID 10010、0750；
   状态、登记、客户端和公开 CA 目录为 10003:10003、0755。凭据文件、私钥和执行锁仍保持
   独立的私有权限。只有明确指定的空目录会被调整，非空且权限不符时全部预检后拒绝，
   不递归修改已有工作副本。该入口在 Linux/WSL2 使用 root 完成固定 UID/GID 初始化。

   代码知识部署设置 `CODE_CHECKOUT_ENABLED=true`；只使用 ONES 时可显式关闭并省略
   以下 `--require-code`。即使关闭，Compose 挂载的空根目录仍须存在。

   ```sh
   python3 scripts/deployment_check.py init-volumes --fresh
   python3 scripts/deployment_check.py check --require-code
   ```

   初始化先核对项目容器、平台数据卷和全部目标知识卷；发现已有部署或未标记的已有卷时拒绝。
   只有该命令先前创建的同项目卷允许幂等续跑。它不会删除、覆盖、清空卷，不拉取模型；普通
   `check` 和 `up` 不会自动创建缺失的知识外部卷。卷已创建但尚未启动时可安全重复初始化。

4. 用唯一主文件构建并启动：

   ```sh
   docker compose -f docker-compose.yml up -d --build
   python3 scripts/deployment_check.py accept --require-code
   ```

   首次需要下载固定 Embedding、重排、文档处理模型及构建依赖，准备任务成功退出后依赖服务
   才启动。`accept` 尚未通过时先查安全状态；不要跳过 Migrator 或强行并行多个同步写者。

## 已有环境升级

保留原 `.env`、Master Key、数据库、模型、向量、进度卷和项目名。先核对备份和当前任务，
安排维护窗口，再按当前版本构建/重建相关服务。使用原密钥目录运行 bootstrap 并带
`--docker-acl` 补齐所需角色身份材料及读取权限；已有管理员沿用原初始化行为。
代码分析身份也由主 Compose 统一挂载：保留现有 `CODE_RUNTIME_BOOTSTRAP_TOKEN_HOST_FILE`
路径，或使用 bootstrap 生成的 `code-runtime-bootstrap-token`，无需叠加代码知识库配置文件。
不要对已有安装执行 `init-volumes --fresh`。

执行器现在以 `10003:10010` 运行，两个 Runtime 加入只读者组 10010，必须重新创建相关容器，
仅 restart 不会应用身份/组/挂载变化。已有工作副本不能在分析过程中递归 chmod/chown。
若预检指出旧源码根权限不符，保留原目录，使用新的空源码根完成初始化、重新检出，并在
知识库页面绑定新目录后再恢复分析；状态根若含已有配置，应由部署人员停机维护，保留原
登记、CA 和凭据，不用空目录替换原状态。初始化脚本不会替换既有数据库或身份材料。

`external_volume_missing` 时先核对 `KNOWLEDGE_*_VOLUME` 和实际 Docker context；若是版本
升级新增的空模型缓存卷，由部署人员确认用途后单独创建该卷，不自动补建向量或进度卷。
主项目迁移按[知识运维手册](../../knowledge/OPERATIONS.md)停止旧写者后复用原卷。

本次控制器挂载布局有变化，需要重新创建 `knowledge-ops-controller`；仅重启旧容器不会
更换挂载。Compose 与镜像必须来自同一发布。控制器固定读取 `/deployment/.env`，只检查自身
项目标签和六个只读 bind mount 的元数据，以 daemon 源路径启动知识容器，以容器内路径构建
镜像。[Docker bind mount 使用 daemon 主机路径](https://docs.docker.com/engine/storage/bind-mounts/)，
不能把 `C:\...` 或某个 WSL 别名直接当成嵌套 Compose 的 Linux 源路径。

## 实际验收

`check` 检查 Linux Engine/架构、Compose 版本、LF、根目录与文件型 Secret 元数据、四个外部卷、
源码及状态目录存在性、Linux UID/GID/权限，以及执行器/A/B/控制器挂载一致性与共享组；
`--require-code` 额外要求执行器启用。Mac 宿主的权限映射不凭宿主 stat 断言，输出
`code_ownership_check=target_probe_required`，需实际容器验证。
不会读取 Secret 内容，也不会证明服务能启动。`accept` 进一步核对全部默认常驻服务的状态和
健康检查、四个一次性初始化任务的退出码，并在真实控制器内执行路径和 Compose 配置检查。
输出只有状态、平台和固定错误码，始终保留 `business_acceptance=not_checked`。

代码权限隔离验收可在目标机器用已经构建且包含 SVN 的 `knowledge-sync` 镜像执行：

```sh
python3 scripts/verify_code_checkout_permissions.py --image <knowledge-sync镜像名或ID>
```

该入口使用新建临时卷、合成 SVN 仓库、无网络容器及当前源码；验证 r2 检出、r3 新增中文
目录/文件、两个独立 Runtime 读容器、只读挂载与私有测试凭据隔离，结束删除自建容器和卷。
它不读取真实凭据、不访问生产仓库，不等于实际宿主 bind、SELinux 或完整 Job 已验收。
Rocky Linux 开启 SELinux 时另外核验目录和 socket 标签；不自动关闭 SELinux。

每个目标环境分别完成下表，记录版本、时间、成功/失败及安全错误码，不上传 `.env`、完整
`docker inspect`、解析后的 Compose 配置或原始业务消息。

| 验收项 | 通过标准 |
| --- | --- |
| 首次启动 | `accept` 成功，初始化任务退出码为 0，默认服务就绪 |
| HTTP 网页 | 登录成功；知识库立即同步按钮不出现 `crypto.randomUUID` 错误 |
| 网页控制器 | 无活动任务的维护窗口内停止知识服务后再次启动；平台与控制器持续在线，原卷和知识数量保持 |
| 构建 | 网页构建仅操作知识服务，构建完成不自动采集；随后显式启动成功 |
| 离线知识测试 | 授权用户目录、检索均成功，来源及入库时间可见，不依赖 ONES |
| 真实在线环境 | `online` 下通过用户 ONES 可读性校验；异常不自动降级为 offline |
| 同步 | 授权开启后完成一轮，进度和块计数正确；运行中下次执行显示本轮完成后 4 小时 |
| 重建与持久化 | 重建服务后数据库、知识和断点保留；不使用 `down -v` |

本地合成合同测试、ARM 主机的 amd64 模拟容器均不能替代 Windows WSL2 或真实 x86 VM
整套验收。目标环境未运行这些步骤时，应标为未验收。本次实际检查范围见
[本地验证记录](docker-compatibility-validation.md)。

## 常见预检错误

| 错误码 | 处理 |
| --- | --- |
| `use_wsl2_linux_terminal` | 在启用 Docker 集成的 WSL2 发行版里运行 |
| `code_directory_initialization_requires_root` | 仅对显式目录初始化命令使用 sudo，普通检查无需读取凭据内容 |
| `code_directory_missing_or_invalid` | 先初始化正确根目录，拒绝符号链接和错误路径 |
| `code_directory_permissions_invalid` | 核对源码 10003:10010/0750、公开状态目录 10003:10003/0755；旧目录先维护 |
| `code_directory_existing_data_requires_maintenance` | 保留旧数据，不自动递归修复；使用新源码根检出或停机维护状态目录 |
| `code_mount_source_mismatch` / `code_mount_invalid` | 核对 A/B 只读、执行器可写及控制器挂载源一致，禁用缺失目录自动创建 |
| `code_executor_identity_invalid` / `code_reader_group_missing` | 应用同版本 Compose 并重新创建执行器和两个 Runtime |
| `code_checkout_not_enabled` | 在根 .env 显式设置 CODE_CHECKOUT_ENABLED=true 后重新创建执行器 |
| `deployment_root_mismatch` | `KNOWLEDGE_DEPLOY_ROOT` 指回当前主 Compose 根目录 |
| `secret_file_missing:*` / `secret_file_invalid:*` | 核对文件路径、普通文件、非空、非符号链接，保留原凭据 |
| `fresh_init_refused_*` | 检测到既有安装证据，按升级流程处理，不删除卷来绕过 |
| `knowledge_ops_mount_invalid` | 重新创建匹配版本控制器，核对固定挂载、项目标签和 Docker socket |
| `docker_command_failed` | 核对 Docker context、权限、服务状态和版本；工具不回显可能含凭据的 stderr |
| `services_not_ready:*` | 等待初始化或处理指定服务状态，再运行 `accept` |
