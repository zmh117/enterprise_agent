# Windows、macOS 与 Linux Docker 部署

所有服务仍只使用根 `docker-compose.yml` 启动。本手册覆盖 Windows 10/11 + Docker
Desktop（WSL2 后端、Linux 容器）、macOS Docker Desktop 和 Linux x86-64 虚拟机；不覆盖 Windows 原生容器。
代码兼容、容器健康和真实业务验收分别记录，不能互相代替。

## 主机准备

| 项目 | Windows 10/11 | x86-64 Linux 虚拟机 |
| --- | --- | --- |
| Docker | Docker Desktop 启用 WSL2 和目标发行版的 WSL Integration，切换 Linux 容器 | Docker Engine 与 Compose plugin |
| 操作终端 | WSL2 Linux 终端，安装 Git、Python 3.10+、OpenSSL、acl | Linux shell，安装 Git、Python 3.10+、OpenSSL、acl |
| 仓库与密钥 | 建议分别位于 WSL 的 `~/enterprise_agent`、`~/.config/enterprise-agent` | 如 `/opt/enterprise_agent` 和部署账号的 `~/.config/enterprise-agent` |
| 架构 | `docker version --format '{{.Server.Os}}/{{.Server.Arch}}'` 应为 `linux/amd64` | 同左；x86 指 64 位，不支持 32 位容器 |
| Compose | 2.24.0 或更新版本；预检支持 Compose 5 的版本号 | 同左 |

普通 `docker compose up -d --build` 可在 Windows CMD / PowerShell、macOS 和 Linux 运行。
本页标记 `sh` 的首次密钥生成命令须在 Linux/WSL 终端执行，不混用终端语法。
预检和验收脚本可由已安装的 Python 执行；Windows 使用 `python` 替代 `python3`。
推荐把仓库放在 WSL Linux 文件系统中，而非 `/mnt/c`；这是
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

   默认凭据目录为 HOME（Linux/macOS）或 USERPROFILE（Windows）下的 `.config/enterprise-agent`。
   自定义已有目录可设 `PLATFORM_SECRETS_DIR`，非空单文件 `*_FILE` 优先。管理员初始化沿用[既有初始化流程](schema-baseline-bootstrap.md)。
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

3. 主 Compose 自动准备源码与状态目录。`code-storage-init` 是一次性初始化容器；
   普通 `up` 会等待它成功，再启动 API、两个 Runtime、knowledge-sync 和运维控制器。
   首次安装若要在 `up` 前运行只读预检，可先单独初始化：

   ```sh
   docker compose run --build --rm --no-deps code-storage-init
   ```

   该命令无需宿主 sudo 或 Python，可在 Windows CMD / PowerShell、macOS 和 Linux 使用。
   初始化无网络、不挂载 Secret，只处理 `.env` 配置的两个根：
   `CODE_SVN_CHECKOUT_HOST_ROOT` 和 `CODE_SVN_LOCAL_STATE_ROOT`，留空使用部署根下
   `.local/code-svn/checkout`、`.local/code-svn/state`。
   Linux 源码根设为 10003:10010/0750；状态及 configuration、client、trusted-ca
   四个目录设为 10003:10003/0755。只调整这五个目录的元数据，不递归修改子文件；
   凭据、已有源码与 SVN 身份标记均保留。实际以执行器 UID 写合成临时文件、Runtime UID
   读取后清理；权限探测失败会阻断消费者。Desktop 若转换 Unix 元数据，明确记录
   `translated_access_verified`，仍要求实际访问通过。

   代码知识部署设置 `CODE_CHECKOUT_ENABLED=true`；只使用 ONES 时可关闭并省略
   `--require-code`。即使关闭，空挂载目录仍由初始化准备。严格的手动
   `init-code-directories` 保留为 Linux/WSL 维护工具，不再是普通启动前置步骤。

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
启动初始化仅修正固定根目录权限。若旧工作副本内部文件权限不符，保留原目录，使用新的
空源码根重新检出并在知识库页面绑定后恢复分析；不递归 chmod/chown，也不用空目录
替换已有状态、登记、CA 或凭据。

`external_volume_missing` 时先核对 `KNOWLEDGE_*_VOLUME` 和实际 Docker context；若是版本
升级新增的空模型缓存卷，由部署人员确认用途后单独创建该卷，不自动补建向量或进度卷。
主项目迁移按[知识运维手册](../../knowledge/OPERATIONS.md)停止旧写者后复用原卷。

本次控制器挂载布局有变化，需要重新创建 `knowledge-ops-controller`；仅重启旧容器不会
更换挂载。Compose 与镜像必须来自同一发布。控制器固定读取 `/deployment/.env`，只检查自身
项目标签和六个只读 bind mount 的元数据，以 daemon 源路径启动知识容器，以容器内路径构建
镜像。[Docker bind mount 使用 daemon 主机路径](https://docs.docker.com/engine/storage/bind-mounts/)，
不能把 `C:\...` 或某个 WSL 别名直接当成嵌套 Compose 的 Linux 源路径。

### Windows CMD 中更新后启动

更新代码后在项目根执行（无需先 down，不删除卷）：

```bat
cd /d D:\enterprise_agent
docker compose up -d --build
docker compose ps -a code-storage-init
```

`code-storage-init` 显示 `Exited (0)` 是正常成功。源码和状态 bind 允许创建缺失目录；
平台凭据 bind、主部署目录和四个知识外部卷保持原来的严格规则。初始化镜像只含标准库脚本，
不会拉取 SVN 或触发模型提取。查看初始化固定状态可用 `docker compose logs code-storage-init`。

若已有 `.env` 仍手写 `XXX_FILE=${HOME}/...`，Compose 会在解析旧文件时产生 HOME 警告，
需要保留原文件位置并把这些路径改成实际路径，或改用统一目录、将对应文件级配置留空：

```dotenv
# 此处仅为路径示例，必须替换为原有凭据目录；使用 / 避免反斜杠转义。
PLATFORM_SECRETS_DIR=D:/enterprise-agent-secrets
APP_CONFIG_MASTER_KEY_FILE=
```

单文件覆盖优先于统一目录；不重建 Master Key，不覆盖原 `.env`，不把密钥放到源码目录。
新配置无需设置 HOME；默认使用 Windows 的 USERPROFILE。若 HOME / USERPROFILE / 显式
路径均缺失，Compose 明确报错。代码 Runtime 的单文件配置为
`CODE_RUNTIME_BOOTSTRAP_TOKEN_HOST_FILE`。这些修复不替代目标 Windows 实机的网络、认证及业务验收。

## 实际验收

`check` 检查 Linux Engine/架构、Compose 版本、LF、根目录与文件型 Secret 元数据、四个外部卷、
源码及状态目录存在性、Linux UID/GID/权限，以及执行器/A/B/控制器挂载一致性与共享组；
`--require-code` 额外要求执行器启用。Mac 宿主的权限映射不凭宿主 stat 断言，输出
`code_ownership_check=target_probe_required`，需实际容器验证。
不会读取 Secret 内容，也不会证明服务能启动。`accept` 进一步核对全部默认常驻服务的状态和
健康检查、五个一次性初始化任务的退出码，并在真实控制器内执行路径和 Compose 配置检查。
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
| `use_compose_code_storage_init` | Windows 使用 `docker compose run --build --rm --no-deps code-storage-init` |
| `code_directory_initialization_gate_missing` | 使用同版本主 Compose，消费者必须等待初始化成功 |
| `code_directory_init_failed` / `code_directory_access_probe_failed` | 检查配置路径、Docker 文件共享及权限；不输出凭据内容 |
| `code_directory_initialization_requires_root` | 仅对显式目录初始化命令使用 sudo，普通检查无需读取凭据内容 |
| `code_directory_missing_or_invalid` | 先初始化正确根目录，拒绝符号链接和错误路径 |
| `code_directory_permissions_invalid` | 核对源码 10003:10010/0750、公开状态目录 10003:10003/0755；旧目录先维护 |
| `code_directory_existing_data_requires_maintenance` | 保留旧数据，不自动递归修复；使用新源码根检出或停机维护状态目录 |
| `code_mount_source_mismatch` / `code_mount_invalid` | 核对 A/B 只读、执行器可写及初始化/控制器挂载源一致，仅源码和状态目录允许创建 |
| `code_executor_identity_invalid` / `code_reader_group_missing` | 应用同版本 Compose 并重新创建执行器和两个 Runtime |
| `code_checkout_not_enabled` | 在根 .env 显式设置 CODE_CHECKOUT_ENABLED=true 后重新创建执行器 |
| `deployment_root_mismatch` | `KNOWLEDGE_DEPLOY_ROOT` 指回当前主 Compose 根目录 |
| `secret_file_missing:*` / `secret_file_invalid:*` | 核对文件路径、普通文件、非空、非符号链接，保留原凭据 |
| `fresh_init_refused_*` | 检测到既有安装证据，按升级流程处理，不删除卷来绕过 |
| `knowledge_ops_mount_invalid` | 重新创建匹配版本控制器，核对固定挂载、项目标签和 Docker socket |
| `docker_command_failed` | 核对 Docker context、权限、服务状态和版本；工具不回显可能含凭据的 stderr |
| `services_not_ready:*` | 等待初始化或处理指定服务状态，再运行 `accept` |
