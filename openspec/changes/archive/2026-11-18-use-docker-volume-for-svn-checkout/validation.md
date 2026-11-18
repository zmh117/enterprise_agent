# 本地验证（2026-11-11）

本变更实现用户选择的 Docker 存储卷，不将最新 E200030/E200042 等同于已证明的 9p 故障。
E200030 为 SQLite 层错误；E200042 为附加错误包装。历史记录只有数字错误号，不能恢复底层 SQLite 文本原因。

## 已验证

- 主 Compose、初始化、执行器、Runtime A/B、控制器统一使用 code-svn-checkout 卷；默认名及自定义名的实际 Compose 渲染通过，旧宿主目录配置不再控制源码挂载。
- 首轮六个相关测试文件：141 passed，包含真实隔离 Compose 初始化、保留旧文件、初始化失败阻断、命名卷重建持久化。
- 后续新增实际挂载及控制器卷 Options 校验后：test_windows_container_compatibility.py 60 passed（含已运行用例，不与上一项简单累加）。
- test_knowledge_compose.py：9 passed，包含新增的默认/自定义源码卷名渲染。
- scripts/verify_code_checkout_permissions.py 使用已有 SVN 镜像、当前只读挂载代码、新建独立 local 卷及无网络容器：r2 检出、r3 新增中文/空格路径更新；两个独立 Runtime 读容器通过，写入被拒绝；无关 UID 和私有测试凭据隔离通过。
- 使用当前 Dockerfile 成功构建 code-storage-init:compat-check 测试镜像。隔离测试容器与卷均已清理。
- Ruff、git diff --check、change 和 platform-operations canonical spec 的 OpenSpec strict 校验通过。

## 未验证及保留事项

- 没有修改本机或 Windows 业务容器、业务卷、数据库记录、旧检出目录或真实凭据。
- 未执行 Windows 真实仓库长检出、现有知识库重新绑定、发布或真实模型问答。任务 2.3 保持未完成。
- 本次不修改续租/claim 逻辑；此前 CODE_OPERATION_LEASE_LOST 的后台续租停止原因尚未得到现场证据证实。
- Windows 更新使用 docs/operations/docker-deployment.md 的命名卷切换步骤；维护窗口内停止使用者，重新检出并显式绑定，不能把历史完成记录当作新卷现有数据。

## 依据

- [Docker 卷生命周期及共享挂载](https://docs.docker.com/engine/storage/volumes/)
- [Apache SVN 错误定义](https://subversion.apache.org/docs/api/latest/svn__error__codes_8h_source.html)
- [SQLite 文件系统注意事项](https://sqlite.org/useovernet.html)：仅作为方案依据，不能代替该 Windows 现场根因证据。
