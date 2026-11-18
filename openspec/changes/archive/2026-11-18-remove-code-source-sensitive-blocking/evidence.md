# 本地验证记录

日期：2026-11-13。

## 已实现并验证

- Read/Grep 不再按文件名或敏感内容正则阻断。合成 `zh-CN.js`、`config.ts`、`token.cpp` 和普通 C++ 字符串均可完整读取、截取行、搜索与清理缓存，保持原始内容。
- SVN 单文件 diff 的名称/内容阻断和 log 提交说明的内容筛查已移除。隔离临时 SVN 仓库验证中文文案两端差异、提交说明，以及超长说明仍省略、越权复制来源仍拒绝。
- 授权、工作副本完整性、版本、未跟踪文件、符号链接、取消、审计和临时缓存相关回归通过。历史错误码中文呈现保留，新源码路径不再抛出 `CODE_SOURCE_SENSITIVE`。
- 同步两个 canonical 领域。将 task-file-workspace 文末两个源码 Requirement 放回主 Requirements 节，保留原实现依据说明，修正严格规范校验发现的既有结构问题。

## 检查结果

- `.venv/bin/pytest -q backend/tests/test_code_source_search.py backend/tests/test_code_source_runtime_v2.py backend/tests/test_code_answer_presentation.py backend/tests/test_python_runtime_run_audit.py`：65 passed。
- Linux knowledge-sync 镜像中以当前工作区 backend 只读挂载运行 `python -m unittest backend.tests.test_code_svn_history -q`：14 passed、1 skipped。容器无网络、不挂载任何业务卷或凭据，SVN 仓库和工作副本均在临时目录创建。跳过项要求该镜像未安装的 Runtime ripgrep；本机实际 ripgrep 搜索已由上述 pytest 覆盖。既有 SVN 集成搜索断言同步为迭代器消费，并显式标记额外工具依赖。
- 6 个修改 Python 文件 Ruff lint/format 检查通过；4 个修改实现模块 mypy（`--follow-imports=silent`）通过。源码枚举参数列表补充类型注解。
- change、task-file-workspace、builtin-tool-resource 的 OpenSpec strict 校验通过；`git diff --check` 通过。

## 尚未执行

未更新运行中的应用容器或 assist03 的不可变 Skill 发布，未读取现场源码、凭据或真实业务记录，未对 zx/r52455 的原问题执行模型验收。部署步骤见 `docs/operations/code-knowledge-on-demand.md`，无需迁移数据库、重新检出或重建索引。
