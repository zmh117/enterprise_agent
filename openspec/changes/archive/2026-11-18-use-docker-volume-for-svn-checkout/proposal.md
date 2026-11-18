## Why

Windows Docker Desktop 共享盘上的 SVN 工作副本反复失败；最新 update 返回 E200030（SQLite 错误）和 E200042（附加错误包装），不足以证明具体 I/O 原因。用户已选择工作副本主要供系统和 Runtime 使用，改用 Docker 本地存储卷，移除 Windows 共享文件系统这一层。

## What Changes

- **BREAKING** 主 Compose 的检出根改为统一命名卷，废止 CODE_SVN_CHECKOUT_HOST_ROOT；保留原宿主目录，不自动复制、删除或迁移旧绑定。
- 初始化、执行器、两个只读 Runtime 和运维控制器共享同一个卷；固定容器路径与读写互斥不变。
- 控制器以 Docker 卷 Name 复用存储，不把 Mountpoint 转成 bind；部署预检核对类型、名称与权限。
- 更新部署及维护说明，提供重新检出并绑定的切换步骤和真实隔离测试。
- E200030 归入已有工作副本数据库故障类别，保留数字错误号，不据此推断数据库损坏或自动 cleanup/retry。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `platform-operations`: 受管源码共用 Docker 命名卷、跨平台初始化/预检、升级保留旧数据。

## Impact

主 Compose、初始化脚本、deployment_paths、部署预检、SVN 错误分类和运维文档/测试。没有数据库迁移、额外服务、自动复制或模型提取；不改变 ONES 存储。Windows 真实仓库长检出仍需现场验收；不宣称既往租约失效原因已经查明。
