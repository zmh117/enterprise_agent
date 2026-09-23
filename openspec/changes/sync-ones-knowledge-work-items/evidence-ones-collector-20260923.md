# 受管 ONES 全量采集器：本地代码证据（2026-09-23）

## 已实现范围

- 只参考新版导出器的固定 GraphQL count/list、按创建日期拆分及 `/info` 详情合同；后端不执行导出脚本。运行配置固定 Provider origin、Team、项目和三类根类型及子任务类型 UUID。受管凭据中心只存引用，采集身份通过固定 HTTP 边界在运行时消费。
- 每轮完整枚举并重新读取全部根工作项详情；Story 详情列出的子任务 UUID 也逐一读详情。候选页与安全检查点同事务提交；失败后同一活动 run 从头枚举并按候选哈希幂等重放，不跳过已有 UUID。
- 缺页、重复/无进展游标、详情范围不一致、字段字典冲突、单日窗口达到 1000、总量超过 200000、全空结果及固定范围内已有项不可见都失败关闭。已有项缺失不自动撤收录。Provider 鉴权/限流/不可用只落固定错误码。
- 规范化只投影正文、字段与关联所需键；不调用评论、附件或图片下载接口，不存评论/附件正文。CLI 配置后默认关闭；显式启用和 `once --commit` 只到 `STAGED` 候选，不变更当前收录、索引、发布或授权。

## 本地验证

- 合成 Provider、SQLite 候选、类型化导入/分块与测试层级治理相关定向回归：`92 passed, 2 skipped`；新增测试已登记 `backend/tests/test_suite_tiers.toml`。
- `ruff check` 与目标模块 `mypy --follow-imports=skip` 通过；`git diff --check` 通过。
- `openspec validate sync-ones-knowledge-work-items --strict --no-interactive` 通过。

## 边界与待办

- 本机没有可访问的真实 ONES；没有读取真实 Token、启动采集、改本机数据库、部署服务或修改权限。上述测试不验证真实 Provider 的 `project_in`、字段目录、排序、版本戳或 TLS 证书。
- 当前交付限于采集与候选阶段。任务 5 的受管内容/资源自动激活、任务 7 的每小时 worker/可选 Compose、任务 8 的隔离 PostgreSQL/Qdrant 全链路和任务 10 的真实 ONES 验收仍待完成；不能把 `STAGED` 视为当前可检索内容。
