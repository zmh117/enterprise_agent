## Context

当前执行器 UID/GID 10003 与 Runtime UID/GID 10002 不同，凭据入口保留私有 umask；普通 Linux 目录不会提供 Docker Desktop 可能存在的宿主权限映射。现有预检只覆盖早期控制器挂载，未覆盖后加的代码根目录。

## Goals / Non-Goals

目标：新 Linux 部署能安全初始化目录；首次检出及 update 后新文件可跨 UID 读取；权限不足提前报错。无数据库变更，不执行模型，不改现有读写互斥，不递归修复活动工作副本，不将本机测试标为虚拟机整套验收。

## Decisions

1. 固定源码读者组 GID 10010，作为执行器的主组、两个 Runtime 的 supplementary group。共享根目录属于 10003:10010，模式 0750；新文件由执行器主组创建，不依赖宿主对目录 setgid 位的实现。Runtime 挂载继续为只读。
2. 仅 SVN 子进程使用 umask 0027，避免修改多线程宿主进程的 umask 或放宽凭据入口。身份标记在发布前显式设为 0640。凭据与执行锁仍保持现有私有权限。
3. 通过现有部署检查脚本的显式初始化命令准备源码根与状态子目录。普通 check 不创建目录；初始化先检查全部目标，不递归 chown/chmod 非空旧目录。非空且权限不符时要求停机维护或使用新根重新检出，保留原数据。
4. 预检核对执行器、A/B、控制器的目录一致性、只读性、读者组及 Linux 宿主所有权；`--require-code` 明确要求执行器开启，普通检查也输出启用状态。配置示例显式列出开关与目录。
5. 将 PermissionError 区分为 CODE_CHECKOUT_PERMISSION_DENIED，保留身份标记被替换等真实异常的原错误码。

## Risks / Trade-offs

- 固定 UID/GID 对 rootless 或 userns-remap 不适用：沿用预检拒绝，并单独验收。
- SELinux、NTFS/NFS、Docker Desktop 映射与 Linux 本地文件系统语义不同：文档要求目标环境验证，不自动修改安全策略。
- 已有旧目录可能权限不符合：不在运行中递归修复；首次修复使用新根并重新检出绑定，保留旧目录。
- 本机可做真实 SVN、两个独立读容器和非授权 UID 检查；目标虚拟机部署仍需单独验收。
