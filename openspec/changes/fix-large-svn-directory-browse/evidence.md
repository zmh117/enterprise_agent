# SVN 按层浏览验证记录

日期：2026-11-11。范围：本机工作区、合成输入与隔离 SVN 仓库；未访问真实 Windows 部署或企业 SVN，未启动模型任务，未更新部署容器。

## 问题与实现

原 `WorkingCopyClient.browse` 调用递归 inventory，首次预览即执行 `svn list --xml --recursive`。SVN 标准输出上限为 8 MiB，标准错误也受独立容量限制，任一输出超限可返回 `code_svn_response_too_large`。已确认此实现会让大分支的预览触碰整树容量上限；没有现场输出大小证据，不能断言用户这次响应究竟是哪条流超限。

现在首次浏览和展开子目录均只请求直接子项。管理接口新增 `browse-children`，输入仅根浏览 ID、相对路径和幂等键，服务端继承原连接、来源和数字 SVN 修订，校验操作者、当前草稿、路径与根操作状态。执行仍复用现有管理员校验、连接摘要、仓库身份、操作账本和临时结果缓冲。没有新增表、容器或模型工具，也没有降低容量、证书或权限约束。

前端保留同层复选框对齐和文件/目录多选，按展开请求子层。折叠保留已加载树和选择；局部错误可独立重试，重试生成新幂等键；树由根浏览 ID 隔离。超限等错误有中文提示。完整检出继续使用原有清单与磁盘预检，本次不扩展其总容量。

## 已完成验证

- 后端：`test_code_checkout.py`、`test_code_svn_access.py`、`test_code_resources.py`、`test_code_svn_history.py`：56 passed，13 skipped。跳过项依赖本机未安装的 SVN CLI，不算已验证。
- 大清单回归以超过 8 MiB 的合成递归 XML 验证：浏览根与子目录均不发递归命令，只返回当前层；文件目标或异常嵌套响应拒绝。
- 子浏览测试覆盖同版本继承、幂等提交、路径越界、跨操作者/资源、失败父浏览、草稿变更与提交竞态拒绝。
- 前端：`code-checkout-panel.test.tsx`、`code-resource-editor.test.tsx`：9 passed。覆盖延迟加载、折叠不重复提交、选中项保留、固定根浏览检出、超限中文提示和局部重试。
- 真实 SVN CLI：使用现有 `enterprise-agent/knowledge-sync:local` 镜像，挂载当前 backend 只读，`--network none --read-only`、UID/GID `10003:10010`、1 GiB 临时内存盘。在合成 `file://` 仓库运行 `test_code_checkout_svn_integration.py`：4 passed，4 skipped。覆盖仅直接层、后续提交不改变 r2 子目录结果、完整文件、多选文件/目录与原子检出。4 个需认证/网络 fixture 的测试未运行。初次使用 256 MiB 临时盘触发原有磁盘预检，改为足够容纳预检预留量的 1 GiB 后通过，未修改容量策略。
- Ruff 检查变更 Python 文件通过；Mypy 检查 5 个生产 Python 文件通过。
- 前端变更文件 ESLint 与 `tsc -b` 通过。
- OpenSpec 严格校验及 `git diff --check` 通过。

## 交付与待验收

目标部署需一起构建更新 api-server、knowledge-sync、admin-web；无需数据库迁移或 Agent 重新发布。操作步骤已补入 `docs/operations/code-knowledge-on-demand.md`。尚未提交、推送或部署本次代码；没有声明 Windows 真实 SVN 已恢复。

现场应重新浏览真实地址，展开至少两层、勾选文件与目录，确认采用同一个 SVN 数字修订，再按实际范围检出。若单层仍超限，按中文提示缩小地址范围，并区分单层预览限额与完整检出的清单/磁盘限额。
