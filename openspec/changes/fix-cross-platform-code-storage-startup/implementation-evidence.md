# 实现与验证记录

日期：2026-11-10。工作区为 /Users/mhz/Develop/enterprise_agent，基于 df404233。

## 已确认

- 原故障复现：合成 Compose 的初始化容器开启根目录创建、消费者子目录保持 create_host_path=false，创建消费者时仍因路径不存在失败。依赖门禁本身不解决创建阶段问题。
- 当前 Compose 仅对源码/状态目录允许创建，增加 code-storage-init 及五个消费者依赖（含两个 Runtime）；Secret bind 保持禁止创建。
- 初始化镜像独立 Python 标准库目标，无网络、无凭据、无数据库，不继承 Secret 复制入口。只修改五个已校验目录的元数据，探测执行器写/Runtime 读后删除临时文件；无子文件遍历与递归权限修复。
- 文件型凭据解析优先顺序：单文件覆盖、PLATFORM_SECRETS_DIR、HOME、USERPROFILE。测试在清理过的合成环境运行，不读取真实 .env / Secret。
- 110 项相关回归通过；其中 18 项启动专项测试覆盖主文件约束、Linux/macOS/Windows 路径插值、显式覆盖、无来源失败、符号链接/重叠、Desktop 元数据转换访问验证、真实 Compose 首次/重复启动及失败门禁。最终补充 reader 完成、真实只读 mount 和根目录防误配校验后，110 项全部再次通过。
- Linux 容器原生命名卷：两次初始化均返回 posix_access_verified，五个目录 UID/GID/mode 正确，无临时探测文件残留。
- Docker Desktop 本机 bind：中文空格路径首次启动成功；重复初始化保留合成已有文件 inode、mtime、权限与内容；错误 configuration 节点阻断 reader 启动；消费者挂载实际为只读。
- Ruff、git diff --check、变更与 platform-operations 主规范严格校验通过。
- 只构建兼容性测试镜像，测试容器/卷均已清理；未重建业务服务，未访问真实 SVN、模型或业务数据库。

## 验证入口

```sh
docker build -f backend/Dockerfile --target code-storage-init -t enterprise-agent/code-storage-init:compat-check .
RUN_CODE_STORAGE_CONTAINER_TESTS=1 .venv/bin/pytest -q backend/tests/test_code_storage_startup.py backend/tests/test_windows_container_compatibility.py backend/tests/test_knowledge_sync_compose.py backend/tests/test_agent_runtime_compose_security.py backend/tests/test_knowledge_compose.py backend/tests/test_knowledge_online_compose.py backend/tests/test_compose_migrator_gate.py
```

初始化与回退使用 Docker 官方的长格式 bind 和 service_completed_successfully 行为，变量使用嵌套默认值：
- https://docs.docker.com/reference/compose-file/services/
- https://docs.docker.com/reference/compose-file/interpolation/

## 仍需目标环境确认

本机为 macOS Docker Desktop/Linux arm64。Windows CMD/PowerShell 的路径解析已有合同测试，但没有在用户 Windows 机器执行更新；Linux x86-64 VM、NTFS 的真实 ACL/共享、SELinux 与整套业务运行尚未验收。

旧 .env 若直接写入 `${HOME}`，仍需按原凭据位置改为显式文件路径或统一目录；不会读取/重写真实 .env 或自动迁移、重建 Master Key。新目录初始化不修复旧工作副本内部文件权限。部署命令为 docker compose up -d --build，Exited (0) 的初始化容器属于正常成功状态。
