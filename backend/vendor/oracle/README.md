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
