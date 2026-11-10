## Why

Windows CMD 执行普通 `docker compose up -d` 时，Git 不包含的源码目录不存在，长格式 bind 在创建容器阶段失败。此前 Linux 手动初始化要求未覆盖普通跨平台启动，凭据默认路径还依赖 Windows 通常没有的 HOME。

## What Changes

- 主 Compose 增加无网络、无凭据的一次性源码目录初始化，仅对明确配置的源码与 SVN 状态目录允许自动创建。
- 初始化仅调整五个固定根目录的权限，保留既有工作副本和凭据文件；实际验证执行器写入和 Runtime 组读取，消费者等初始化成功后启动。
- 凭据目录支持显式统一目录以及 HOME / USERPROFILE 默认值，保留单文件覆盖，不自动生成或迁移密钥。
- 更新部署预检、验收和 Windows CMD / PowerShell、macOS、Linux 说明。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `platform-operations`: 将源码目录显式手动初始化扩展为主 Compose 受控启动步骤；缺失 Secret 和外部卷仍不得自动创建。

## Impact

根 Compose、轻量初始化镜像、部署脚本与兼容测试、环境示例和部署手册。无数据库迁移、不触发模型提取、不更新生产数据。目标 Windows 和 Linux 虚拟机的完整验收单独记录。
