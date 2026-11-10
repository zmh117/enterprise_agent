## Context

实际故障发生于 Windows CMD + Docker Desktop。Compose 先创建所有容器再启动依赖；合成实验证明只有初始化挂载开启自动创建、消费者保持 create_host_path=false 仍会在创建消费者时失败。

## Goals / Non-Goals

目标：普通 up 自动准备绑定源码目录，兼容 Docker Desktop 和 Linux Engine，保留固定 UID/GID 及只读 Runtime。
不做：迁移或重新生成凭据、递归修改源码、替换数据卷、启动模型提取、修改业务问答逻辑。

## Decisions

1. 所有源码和 SVN 状态目录 bind 开启 create_host_path，其他 bind 与 Secret 保持严格规则。单次 code-storage-init 使用独立轻量 Python 镜像、无网络、无 Secret、只挂两个目录；消费者显式等待成功。无需宿主 Python 或 sudo，Windows CMD / PowerShell 可沿用 compose 命令。
2. 初始化持有五个固定目录的无跟随文件描述符，校验目录与根重叠后仅调整其 owner/mode；不遍历/修改现有源码与凭据。此处明确替代原“非空根权限不符全部拒绝”，旧手动初始化仍保留严格模式。在容器内用合成临时文件实际验证 UID 10003/GID 10010 写、UID 10002/附加组 10010 读并清理；Desktop 权限转换以实际访问验证，原生 Linux 保持 POSIX 权限。
3. 单文件路径优先，其次 PLATFORM_SECRETS_DIR，默认依次 HOME、USERPROFILE 下 .config/enterprise-agent。两者均缺少且无覆盖时明确报错；不创建 Secret，旧 .env 中直接引用 HOME 的自定义值需按原位置调整，不能猜测或覆写。
4. 预检检查初始化依赖、绑定一致性与代码开关；启动后验收把初始化容器当一次性任务。网页运维仍仅启动固定知识服务且 --no-deps，不借此扩大管理范围。

## Risks / Trade-offs

- Desktop 可转换 Unix 元数据 → 使用容器内实际身份测试；目标 Windows 实机和 Linux VM 完整业务验收仍独立。
- 配错目录会创建空目录 → 仅源码/状态明确例外，拒绝重叠/符号链接；不初始化凭据和外部卷。
- 已有子文件权限错误 → 不递归修复，继续按原流程维护或重新检出。
- 新增一次性镜像需要首次构建 → 提供 up -d --build，初始化成功退出是正常状态。
