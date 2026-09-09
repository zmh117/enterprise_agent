# 第二阶段本地验收（2026-09-09）

## 已确认

- 九个 GraphQL 列表公开 cursor 被移除；可选 limit 默认/最大1000。bucket 每批最多200；依据 ONES 官方 limit/after/endCursor/hasNextPage/unstable 合同，无业务分组，不再用内层51/101/201或祖先扩展裁剪真实页面。
- 类型/模块直接完整列表保持一次受控读取和本地上限，不声称存在 Provider cursor。
- Runtime ONES bridge 在冻结/实时 schema 一致时接管集合结果，使用现有原子预算和完整性校验写只读临时 Markdown 数据文件。ONES-only Job 仅派生 Read/Glob/Grep；不自动获得 File MCP 写入/提交能力。
- 原公开长游标模块及对应续页测试已删除，由自动收集、拒绝模型cursor和既有身份/授权测试覆盖；删除内容可从 Git 历史恢复。
- Tool Call FAILED 的中文安全 error/error_code 已入库并可显示；对象/JSON字符串均覆盖，未引入原始 Provider body 展示。

## 自动化结果

- 后端扩展回归：263 passed。包括 ONES 合同、真实代码固定 Operation + 合成 Mock、身份/授权/401刷新、审计、自动收集、Runtime、沙盒、File bridge、模块架构与 Compose 安全测试。
- 新增自动收集/bridge测试：30 passed（已计入263）；覆盖200/201/999/1000/1001、953非整页上限、重复/空页、unstable、权限隔离、16个结果文件预算、错误转发，以及通过实际 FixedMcpClaudeSdkClient 的成功/失败/取消/超时清理路径。
- 前端运行记录：23 passed；TypeScript build、相关 ESLint 通过，管理前端 Docker 生产构建通过（保留既有大 bundle 警告）。
- 改动生产模块 mypy：7 files passed（设置 MYPYPATH=backend）；相关 Ruff、git diff --check、docker compose config --quiet、严格 OpenSpec 校验通过。
- 全 backend mypy 存在1个未修改文件的既有问题：service_principal.py:19 从 principal_jwt 导入的 MAX_PRINCIPAL_TOKEN_BYTES 未显式导出。未将全量类型检查声称为通过；两个身份源文件无本次差异。

## 本地部署证据

- 已重建并替换 ones-mcp、python-agent-runtime、api-server、agent-worker、admin-web、file-service、tool-mcp；ONES Mock 单独重建并替换。
- 替换前 Runtime 沙盒目录数为0；替换后上述服务 running，配置有 healthcheck 的服务 healthy。admin-web /operations/jobs HTTP 200，ONES Mock /health 为ok。
- ones-mcp 容器合成收集：5次Provider调用、每页200、合计1000、上游仍有1100时truncated=true；9个工具均确认新总量契约和无公开cursor。
- Runtime 容器合成物化：1000条、complete=true、内容可由Read授权读取；cleanup后文件不存在。只输出计数/状态，没有读取或输出真实业务正文、凭据。

## 未验收边界

- 没有读取10.0.102.253的数据库凭据或真实业务数据，没有探测真实 ONES。
- 没有替用户选择或重新发布 Agent/Application；历史Publication与Job不自动升级，必须重新发布后发起新Job。
- 容器内合成核验不等于真实 ONES + 模型 + UI 的全链验收。原 ones_provider_schema_invalid 只能在有受控真实响应结构证据时进一步定位，本次不声称修复所有上游数据兼容错误。
- 临时查询文件在Job结束清理；独立安全审计保留其原生命周期，不承诺清除全部审计副本。
