# Oracle Instant Client（供 internal-api-platform thick 模式使用）

`internal-api-platform` Docker 镜像可以打包 Oracle Instant Client，使
`oracledb` 的 thick 模式能对接较老的 Oracle 服务器（例如 11g / 早期 12c）。

## 许可

Oracle Instant Client 按 Oracle 许可分发。下载前须接受 Oracle 相关条款。
请**不要**把 Instant Client 的 zip 或解压后的库文件提交到 git（已在
`.gitignore` 中忽略）。

## 放入构建上下文

1. 从 Oracle 下载面向 Linux x86-64 的 **Instant Client Basic Light**（或 Basic），
   建议使用较新的 19c / 21c / 23ai Instant Client 版本。
2. 任选其一：
   - 解压到 `backend/vendor/oracle/instantclient/`，保证
     `libclntsh.so*`（以及相关 `.so`）直接位于该目录下；或
   - 将 zip 放在 `backend/vendor/oracle/instantclient-basiclite-linux.x64-*.zip`
     （Dockerfile 会在构建时解压）。
3. 重新构建：

```bash
docker compose --profile real-tools build internal-api-platform
```

未放入 Instant Client 时，Dockerfile **不会执行 apt-get**（避免日常构建卡在
`deb.debian.org`）。只有检测到 `instantclient/` 或 zip 时才会安装 `libaio` /
`unzip`；可用 build-arg 换国内 Debian 源：

```bash
docker compose --profile real-tools build internal-api-platform \
  --build-arg DEBIAN_MIRROR=https://mirrors.aliyun.com/debian \
  --build-arg DEBIAN_SECURITY_MIRROR=https://mirrors.aliyun.com/debian-security
```

镜像会设置：

- `ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient`
- `LD_LIBRARY_PATH=/opt/oracle/instantclient`

## 运行时行为

- 若存在 Instant Client 动态库，平台进程会在启动时初始化一次 thick 模式
  （`oracledb.init_oracle_client`）。
- 若不存在（本地 venv / 构建时未放入 vendor 文件），平台保持 **thin** 模式。
  配置了 `oracle_client_mode: thick` 的基地会明确报错并失败关闭，而不会静默回退。
- `api-server` 与 `agent-worker` 镜像**不包含** Instant Client。

## 拓扑配置项

详见 `backend/config/internal_platform_topology.example.yaml` 中的注释：

- `oracle_client_mode`：`auto` | `thin` | `thick`
- `oracle_compat`：`modern`（FETCH FIRST）| `legacy`（ROWNUM）
- `use_sid`：构建 DSN 时使用 SID 而非 service name
- `connect_descriptor`：可选的完整 connect descriptor / TNS 字符串
