# Oracle Instant Client（供 tool-mcp thick 模式使用）

`tool-mcp` Docker 镜像只接受 **64-bit Oracle Instant
Client 19c**，用于 python-oracledb Thick 连接 Oracle 11.2.0.4。Thin
模式和其他 Instant Client 主版本不会被当成可用能力。

## 许可

Oracle Instant Client 按 Oracle 许可分发。下载前须接受 Oracle 相关条款。
请**不要**把 Instant Client 的 zip 或解压后的库文件提交到 git（已在
`.gitignore` 中忽略）。

## 放入构建上下文

1. 从 Oracle 下载与容器架构一致的 Linux **Instant Client 19c Basic
   Light**（或 Basic）。容器为 `linux/amd64` 时使用 x86-64 包，为
   `linux/arm64` 时使用 aarch64 包。
2. 任选其一：
   - 解压到 `backend/vendor/oracle/` 下任意目录，保证其中包含
     `libclntsh.so.19*`；或
   - 将 Oracle 原始 zip 放在 `backend/vendor/oracle/`。构建脚本会递归
     定位 19c 客户端目录，不依赖压缩包外层目录名。
3. 重新构建：

```bash
docker compose build tool-mcp
```

未放入合规 19c Client 时，或目录里只有 21c/23ai 等其他版本时，
Dockerfile **不会执行 apt-get**，镜像仍可用于 MySQL、SQL Server、Redis 和
Loki，但 Oracle 保持 blocked。只有检测到 19c 库或 zip 时才会安装 `libaio` /
`unzip`；可用 build-arg 换国内 Debian 源：

```bash
docker compose build \
  --build-arg DEBIAN_MIRROR=https://mirrors.aliyun.com/debian \
  --build-arg DEBIAN_SECURITY_MIRROR=https://mirrors.aliyun.com/debian-security \
  tool-mcp
```

镜像会设置：

- `ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient`
- `LD_LIBRARY_PATH=/opt/oracle/instantclient`

## libaio 兼容与构建期加载检查

Debian 等发行版可能提供 `libaio1t64`，其库名为 `libaio.so.1t64`，而 19c
客户端仍依赖 `libaio.so.1`。安装器会在验证客户端是匹配架构的 64 位 19c 后，
检查旧库名能否加载；如不能，从已安装包清单定位 t64 库，并仅在 Oracle 安装目录
建立兼容链接。不覆盖已有文件或链接，不修改系统库，也不下载其他发行版的旧 deb。
此方式参考 [Oracle 驱动安装文档](https://python-oracledb.readthedocs.io/en/latest/user_guide/installation.html#oracle-instant-client-zip-files)。

提供合规客户端时，安装器还会在构建期调用 `oracledb.init_oracle_client()`，确认
**Thick 模式且实际客户端主版本为 19**。缺少动态库依赖、驱动初始化失败、实际版本
不匹配均会终止构建，不再仅凭 `libclntsh.so.19*` 文件存在就判定可用。
成功日志包含 `verified Oracle Thick client: 19.x...`；失败日志包含
`Oracle Thick initialization failed` 和加载错误。检查不连接数据库、不需要数据库凭据。
完全未提供客户端或仅提供其他版本时仍可构建，但 Oracle 保持 blocked。

## Windows 行尾兼容与镜像更新

Git 为 shell 和 `backend/docker/*.py` 固定 LF。即使旧 checkout 或手动复制导致
Oracle 脚本仍是 CRLF，Docker 也会在执行前处理两个脚本的行尾，再显式使用 `bash`
和 `python`，不依赖检测脚本的 shebang 或可执行权限。不需要修改全局 Git 配置。

构建检测结果分为三类：

- 检测成功且命中 19c：继续解压、检查 ELF / 64 位 / 架构并安装。
- 合法 ZIP 不含 19c（检测器退出码 3），或未放置客户端：保留原行为，Oracle
  blocked，其他 Provider 可用。
- ZIP 损坏或不可读、Python 检测器不能运行或异常退出：**构建失败**，不再当作
  “未提供客户端”静默跳过。请根据 `Oracle client verifier cannot run`、
  `Oracle client archive cannot be read` 或 `Oracle client archive detection failed`
  检查脚本及 ZIP；不要通过放宽 Thick 校验绕过。

代码拉取、构建成功或 `docker compose restart` 都不会把已有容器自动换成新镜像。
这次仅 Oracle 构建链路修复，在目标机器准备好合规 ZIP 后执行以下命令
（PowerShell / Bash 均可逐行运行；会短暂重建 tool-mcp）：

```text
docker compose build tool-mcp
docker compose up -d --no-deps --force-recreate tool-mcp
```

若目标机器采用镜像分发，不在本机构建，则先拉取**已包含对应架构 19c 客户端**的
新 tool-mcp 镜像，再执行上面的 `up` 命令。不能仅在另一台机器构建而不更新目标容器。
不要同时运行 `--build` 覆盖分发镜像；客户端 ZIP 不在 Git 中，仅拉代码不会补齐。

在目标容器中可先做不连接数据库的 Thick 初始化自检：

```text
docker compose exec tool-mcp python -c "import oracledb; oracledb.init_oracle_client(); print('client_version=', oracledb.clientversion()); print('thick=', not oracledb.is_thin_mode())"
```

只有输出客户端版本 19.x 且 `thick=True`，才证明该容器已加载客户端；这不等于真实
Oracle 11.2.0.4 连接验收，仍须回到 Web 对当前 Oracle 草稿重新执行技术测试。

## 运行时行为

- 若存在 64-bit 19c 动态库且架构与容器一致，`tool-mcp` 进程会初始化一次 Thick
  模式（`oracledb.init_oracle_client`）。
- 若不存在、版本不符、架构不匹配或初始化后仍为 Thin，Oracle 验证与执行
  都会失败关闭；MySQL 等其他能力不受影响。
- `api-server` 与 `agent-worker` 镜像**不包含** Instant Client。

## 资源配置

新 Oracle Resource 只接受结构化 `host`、`port`、`username`、
`password_ref`，并要求 `service_name` 与 `sid` 二选一。不接受任意 TNS
descriptor、RAC/SCAN、Thin/auto 模式或 12c `FETCH FIRST` 兼容开关。

本地没有真实 Oracle 11.2.0.4 时，单元/镜像测试不能替代真实连接验收，
Oracle Draft 必须保持 blocked，不能发布。

## Web 技术测试与跨环境部署

管理端的 Oracle 技术测试由 API 授权后委派 `tool-mcp` 执行，不在 API 内加载客户端。
API 只传递绑定当前草稿与操作人的限时签名票据，tool-mcp 从现有数据库读取草稿、
校验权限并解析凭据。请求不包含数据库密码；此入口不是 Agent 可用的 MCP 工具。

1. 按上面的许可与架构要求，将 Instant Client 19c 放入**目标机器**的构建上下文。
   客户端二进制不受 Git 管理，因此只拉取最新代码不会自动补齐它。
2. 确保 API 与 tool-mcp 使用同一平台数据库与原有 `app_config_master_key` Secret。
   不要为修复连接问题重新生成主密钥，否则已有加密凭据可能无法解析。
3. Compose 默认内部地址已经配置，无需填写 Oracle 数据库地址到下列变量：

   ```dotenv
   ORACLE_VERIFICATION_BASE_URL=http://tool-mcp:9103
   ORACLE_VERIFICATION_ALLOWED_HOSTS=tool-mcp
   ```

   非 Compose 部署需要把服务地址和主机白名单一起修改；不接受重定向、URL 用户名/密码、
   路径或查询参数。这里的白名单是验证服务主机，不是 Oracle 数据库主机。
4. 在确认升级窗口后构建并更新两个服务（此变更自身没有数据库迁移）：

   ```bash
   docker compose build api-server tool-mcp
   docker compose up -d --no-deps api-server tool-mcp
   ```

5. 在工具资源页对 Oracle 当前草稿重新执行“技术测试”。旧 BLOCKED 记录不会自动变成通过。
   只有当前草稿的 PASSED 结果才能发布；验证期间编辑草稿或停用身份会使结果不能用于发布。

失败说明：

| 安全错误码 | 处理方向 |
| --- | --- |
| `oracle_client_unavailable` | tool-mcp 的 64 位 19c 客户端、容器架构、动态库依赖或 Thick 初始化 |
| `oracle_verification_unavailable` | API 到 tool-mcp 的内部地址、主机白名单、服务版本与主密钥一致性 |
| `oracle_verification_timeout` / `oracle_timeout` | 验证服务响应、数据库网络或探针耗时 |
| `oracle_authentication_failed` | 凭据中心配置、账号锁定/过期或认证协议，不要把密码发到日志或聊天 |
| `oracle_service_not_found` | 数据库 Service Name/SID 及监听注册；二者只能填写一项 |
| `oracle_network_failed` | 从 tool-mcp 容器到数据库地址/端口的网络与防火墙 |
| `oracle_version_unsupported` | 当前契约要求真实服务端 11.2.0.4，而非笼统的 11g |
| `oracle_charset_unsupported` | 当前探针要求 AL32UTF8 / AL16UTF16；不会自动修改数据库字符集 |
| `oracle_readonly_denied` | 账号的只读系统权限、对象权限、角色及只读事务；非本地策略不放行高权限账号 |

连接描述符由结构化字段生成，使用 `CONNECT_TIMEOUT`、`TRANSPORT_CONNECT_TIMEOUT` 和
`RETRY_COUNT=0`，不接受调用者提供任意描述符；查询保留 `call_timeout`。
参数语义参考 [Oracle Net 19c 文档](https://docs.oracle.com/en/database/oracle/oracle-database/19/netrf/local-naming-parameters-in-tns-ora-file.html)。

真实验收：目标环境中完成连接、只读事务、版本及字符集检查后，核对页面 PASSED 与当前草稿版本。
本地单元测试、Mock HTTP、镜像构建成功均不等于已经连接你的 Oracle。
