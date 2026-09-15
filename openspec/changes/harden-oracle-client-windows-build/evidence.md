# Windows Oracle 构建兼容验证记录

日期：2026-09-15。代码位置：本机主工作区；没有提交或部署至其他主机。

## 已确认的修复与本地回归

- Git 为 `backend/docker/*.py` 固定 LF；构建时归一化两个 Oracle 脚本，显式使用解释器。
- ZIP 检测退出码 0 为命中，3 为合法 ZIP 无 19c，2 为解析错误；安装器不再吞掉其他检测失败。
- 原代码对新增测试为 13 failed / 4 passed；修复后镜像契约测试 17 passed。
- 相关回归：`test_oracle_image_contract.py`、`test_redis_cluster_oracle_client.py`、
  `test_oracle_resource_verification.py`、`test_database_resource_verifier_image_contract.py`
  共 76 passed。
- Ruff 检查和格式检查、`bash -n`、`docker compose config --quiet`、
  `git diff --check`、当前 change 的严格 OpenSpec 校验通过。
- `git check-attr eol` 确认 Python 检测脚本和 shell 安装脚本均为 LF。

## 首轮隔离 Linux 实测（依赖问题已在本轮修复）

使用用户已有且被 Git 忽略的 x64 19.12 ZIP，不下载 Oracle 客户端。
临时构建上下文为 `/tmp/oracle-crlf-check.dEx796`，未复制项目配置或凭据。
两个脚本被显式转换为 CRLF 且设置 0644，用 Docker 内断言确认 CRLF 输入。
基础镜像为 `python:3.12-slim`，使用 linux/amd64，不替换本机 ARM64 运行服务。

- 正确定位 `instantclient_19_12/libclntsh.so.19.1`。
- 与正式 Dockerfile 相同的行尾处理和安装器调用完成安装，安装前后两次输出
  `approved Oracle Instant Client: 19c x86_64`。
- 动态加载检查 `ctypes.CDLL('/opt/oracle/instantclient/libclntsh.so.19.1')` 失败：
  `OSError: libaio.so.1: cannot open shared object file: No such file or directory`。
- 安装输出显示基础系统为 Debian trixie，安装 `libaio1t64` 与 `unzip` 成功。
  这是安装后的依赖加载问题，不再是 CRLF 导致的空客户端目录。
- 保留仅完成安装阶段的独立镜像 `enterprise-agent-oracle-crlf-installed:20260915`。
  在 `--network none` 一次性容器中只读检查：`dpkg -L libaio1t64` 列出
  `libaio.so.1t64` / `libaio.so.1t64.0.2`，`ldd` 明确报告 `libaio.so.1 => not found`。
  没有创建兼容链接、替换依赖或修改任何运行服务。

## 用户确认后的修复与复测

用户明确要求继续修复 libaio 兼容并补充构建期 Thick 初始化检查。

- 安装器从发行版已安装 `libaio1t64` 包清单定位真实库，只在 Oracle 安装目录补
  `libaio.so.1` 兼容链接，不覆盖既有文件或链接，不修改系统动态库。
- `verify_oracle_client.py --load-client` 在 ELF 检查后实际调用驱动初始化，检查
  Thick 模式与实际客户端主版本 19；异常退出 2，安装器传播失败。
- 兼容方式依据 [Oracle 驱动安装文档](https://python-oracledb.readthedocs.io/en/latest/user_guide/installation.html#oracle-instant-client-zip-files)。
- 新增依赖兼容和初始化回归后，旧实现为 13 failed / 16 passed；当前镜像契约
  测试 30 passed，上述四组相关回归共 89 passed。Ruff、格式、bash 语法、Compose
  配置、diff 空白检查和严格 OpenSpec 校验通过。

继续使用同一临时上下文、实际 19.12 ZIP 和 CRLF / 0644 脚本；基础镜像采用
Debian trixie 的 `python:3.12-slim`，驱动按项目依赖 `oracledb>=2.2` 安装，
本次解析为 26.0.0。未修改项目依赖声明。

- 独立镜像 `enterprise-agent-oracle-crlf-check:20260915` 构建成功。
  镜像 ID：`sha256:b79fbb637648481cdc625bd1f611c24356daa36a3449301f01fdecffc469aa46`。
- 安装期间输出 `verified Oracle Thick client: 19.12.0.0.0`。
- 镜像构建以 UID 10001 复测通过；随后在 `--network none` 的一次性容器再次确认：
  `uid=10001`、`client_version=(19, 12, 0, 0, 0)`、`thick=True`。
  兼容链接最终指向 `/usr/lib/x86_64-linux-gnu/libaio.so.1t64.0.2`。
- 反向验证：仅在新的无网络、一次性容器中移除该兼容链接，调用新加载检查器，
  返回退出码 2 和 `Oracle Thick initialization failed: DPI-1047`，说明缺失依赖
  不能再以检查成功放过。容器自动移除，未改变镜像或运行服务。
- 无客户端独立镜像 `enterprise-agent-oracle-no-client-check:20260915` 构建成功，
  输出 `Oracle remains blocked` 与 `no-client branch passed`；未安装 Oracle 驱动，
  Oracle 安装目录仍为空，保留非 Oracle 构建分支。

## 验证边界

未调用真实 Oracle、没有 Windows 主机现场验收，没有升级 10.0.102.253，未修改
资源发布结果、数据库或 Runtime 协议。独立镜像验证了真实客户端加载，但不是完整
Compose 部署或真实 Oracle 数据库连接验收。目标机仍需更新镜像并重建 tool-mcp 容器。
未修改既有知识导入、迁移或用户未跟踪文件；未提交代码。
