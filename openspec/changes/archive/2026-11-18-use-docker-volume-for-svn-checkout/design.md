## Context

主 Compose 目前以 Windows/macOS 宿主目录承载 SVN 工作副本，其 .svn/wc.db 也经过共享文件系统。预检与控制器均假定 bind。用户选择 Docker 卷；E200030 只能确认 SQLite 层失败，不能证明 9p 是唯一原因。

## Goals / Non-Goals

目标：同一个 Docker local 命名卷供执行器写、Runtime A/B 读；网页运维使用同一个真实卷；保留旧数据并提供可操作的重新检出流程。
非目标：不迁移数据库、不导入旧工作副本、不新增服务、不修改租约/互斥、不自动重试或 cleanup，不宣称 Windows 现场问题已经验收。

## Decisions

1. 主 Compose 定义 code-svn-checkout 卷，默认项目名前缀；CODE_SVN_CHECKOUT_VOLUME 可指定已有真实卷名。采用 Docker 默认 local 驱动且无 driver_opts，不允许把宿主共享盘/NFS伪装成本地卷。volume.nocopy 避免镜像文件灌入。
2. 初始容器挂载 /storage/checkout，执行器和 Runtime 路径保持 /var/lib/code-svn/checkout，控制器挂到 /deployment-code/checkout。启动权限与只读约束沿用，状态/CA目录仍为原 bind。
3. 控制器只对 checkout 接受 Type=volume、只读、合法 Name、local Driver；从 Name 传 CODE_SVN_CHECKOUT_VOLUME。额外核对卷驱动无 Options，不把 /var/lib/docker/volumes/.../_data 当成 bind。其他挂载仍严格校验。
4. 预检核对所有消费者卷逻辑名、解析卷名与初始化依赖，真实卷以 daemon 元数据校验，不在 Windows 上 stat Linux mountpoint。容器初始化验证实际跨 UID 访问。
5. 本机 local_svn.py 的独立维护检出仍允许显式宿主 destination，但默认引导使用页面受管检出，不能以旧默认位置冒充系统新存储。
6. E200030 纳入已有 CODE_SVN_WC_DB_FAILED；仍保留阶段/数字 E 码，不保存原始错误文本。没有依据时不细分为损坏/I/O。

## Risks / Trade-offs

- 旧数据库绑定指向原相对目录而新卷为空 → 维护窗口切换；旧宿主目录保留，用新的目录名检出并显式保存/验证/发布知识库绑定。不可把旧记录当作新卷已完成目录。
- 错误使用 down -v 会删除命名卷 → 文档只提供保留卷的更新命令，明确备份与稳定项目/卷名。
- Mac 隔离测试不能证明 Windows 真实仓库成功 → 保留现场验收项，报告已做与未做。

## Migration Plan

等待 SVN/分析任务结束，构建受影响镜像，停止执行器、两个 Runtime、控制器；执行 code-storage-init 初始化新卷，重建上述消费者。不删旧宿主目录和数据库记录。页面用全新目录名检出后重绑知识库；确认 r、仓库身份、A/B 读取。回退须维护窗口恢复上一套 Compose/镜像/旧绑定，并确认旧工作副本完整；不混用两套挂载。

## Open Questions

Windows 实际长检出是否还存在非存储原因，需现场执行后核实。此前 CODE_OPERATION_LEASE_LOST 的续租停止原因仍未证实。
