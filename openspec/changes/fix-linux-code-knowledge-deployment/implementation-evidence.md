# Linux 代码知识部署修复验证

日期：2026-11-10。当前工作区；未提交、未更新业务容器。

## 已确认

- 共享源码：执行器 UID 10003、主组 10010；两个 Runtime supplementary group 10010，挂载只读。
- SVN 子进程 umask 0027，身份标记显式 0640；凭据入口仍为 0077，不修改多线程宿主的掩码。
- 权限不足单独返回 CODE_CHECKOUT_PERMISSION_DENIED，页面/时间线有对应提示，同一 Job 不以新 request key 重试该失败。
- 初始化先核对全部指定目录，普通预检不创建目录。拒绝别名/重叠/父路径为文件/非空且不符的旧目录。
- 预检覆盖源码及状态挂载一致性、A/B 只读、执行器身份、固定组、Linux 元数据权限和精确的启用值。
- 配置示例、初始化入口、本地辅助工具及正式 platform-operations 规范已同步。

## 本地检查

- 后端相关用例分组执行，共 151 个不同用例；主组 113 passed，扩展组中的旧短格式挂载断言更新后，对应 9 个用例重跑通过，其余扩展用例通过。
- 前端检出面板与运行记录：40 passed。
- Ruff、4 个应用模块 Mypy、前端 `tsc -b` 与 Vite production build 通过。Vite 保留原有体积提示，不影响构建成功。
- 当前 change 与 platform-operations 正式规范的 OpenSpec strict 校验通过；git diff 空白检查通过。

## 真实 SVN 隔离验证

入口：`scripts/verify_code_checkout_permissions.py --image <含 SVN 的 knowledge-sync 镜像>`。
环境：本机 macOS，Docker Linux/arm64；使用已有含 SVN 镜像和本次源码只读覆盖。

每次创建独立临时 Linux 数据卷与 file:// 合成仓库，无网络，不挂载生产目录/凭据，不连接模型或业务数据库。
测试使用真实 WorkingCopyClient、SvnWorkingCopy、CodeCheckoutReader 和凭据入口。

1. root 初始化指定空目录并重复执行，成功。
2. UID 10003/GID 10010 检出固定 r2，创建身份标记。
3. 两个独立容器同时以 UID 10002、只读卷读取源码、SVN SQLite 元数据与 pristine 证据，成功。
4. 两个读容器退出后，真实 SVN update 到 r3，新增中文/空格目录和文件；再次由两个容器读取成功。
5. 读者在本应可写的自己所属测试目录写入，得到 EROFS；读取私有合成凭据失败；无关 UID 10011 读取源码失败。
6. 工作及读容器关闭 capabilities、开启 no-new-privileges；仅目录初始化容器保留所需所有权能力。
7. 自建容器和卷清理完成，按测试前缀/标签查询无残留。

## 仍需目标环境验收

没有访问目标 Linux 虚拟机、真实企业 SVN 或真实模型；未验证该虚拟机的实际 bind 文件系统、SELinux、网络/CA、完整 Job 和负载。
测试中的 Linux 数据卷不能替代目标宿主挂载验收。现有旧工作副本未自动改权限，按部署手册维护或在新根重新检出绑定。
业务容器、现有数据、源码版本与应用发布未更改；部署需重新构建并创建受影响容器以应用新组与代码。
