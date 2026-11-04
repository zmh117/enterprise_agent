# 离线知识检索验证记录

日期：2026-11-04；本机部署，非生产容量或真实 ONES 验收。

## 代码与合同

- 目录与检索不再依赖 ONES 身份、详情工具或在线可读性；当前平台知识库授权、冻结 Job、资源/成员/版本校验保留。
- search v3 返回入库快照元数据及命中文本片段，directory v2；旧合同不回写。
- SDK 知识 MCP 专属超时按 min(360 秒, Job 剩余预算) 配置，服务截止、取消和在途续期不延长。

## 验证

- 全知识模块回归首次：1228 passed、40 skipped、4 failed。四处失败均为旧授权或旧查询桥断言，修正后相关 44 项通过（43 项批次和剩余 1 项复验）。
- 已提交基线加本次补丁的隔离源码：182 项合同、模型边界、检索、读取权限与 Principal 续期测试通过。
- 真实 SDK 合成 MCP：默认配置在 60.03 秒失败；显式 90000 毫秒配置在 65.11 秒成功。无外网、真实凭据或业务卷。取消语义由服务端回归覆盖，未另行完成 SDK 取消探针。
- Ruff、8 个受影响源码文件 mypy、OpenSpec change 与两个 canonical spec 严格校验、Markdown 文件链接、Compose config 和 diff 空白检查通过。
- 独立 PostgreSQL/HTTP 容器验收通过（67.21 秒）：独立最小权限读取角色、内容连接桥、入库片段、ONES 403/500 不影响离线返回、KB 撤权/恢复、资源停用/恢复、服务重启和关闭知识组件后的普通平台读取。使用合成 ONES、Embedding 和重排引擎，不访问正式数据；测试容器、网络、临时卷和合成身份文件已清理。

## 本机部署

- 使用 HEAD `c4e7da15` 加本次 16 个源码文件的隔离构建上下文，构建 19 个服务；部署只使用主 docker-compose.yml。
- 检查时无活动 Job 或知识操作；更新后服务运行/健康正常，knowledge-check ready 成功。
- API、Worker、两个 Runtime、Knowledge MCP、ONES MCP 的工具合同与当前源码一致；关键无关 Runtime/Agent 改动未进入部署。
- 保留 3 个知识库、15778 条文档、原知识库授权；采集计划启用数仍为 0，无数据迁移或索引重建。
- 原发布者以已有 publish/activate 权限完成正常发布：Agent 修订 43；应用修订 58，local 部署修订 32。未赋予调试权限，未改写旧发布和 Job。
- 新 Agent publication：agent_publication_314822b91c924b0c877d9479e60bb4c8。
- 新应用 publication：business_app_publication_55680b39cccf4dd9b3bd16be02bde14f。
- ONES Mock 的 19121 端口仍不可达，未恢复 Mock 或变更来源配置。

## 真实钉钉链路验收

2026-11-04 18:08:59 至 18:11:03（Asia/Shanghai），原用户从原钉钉会话触发 Job `job_4a1862883ccc46b5b11391bd8a91a0ee`，使用本次新应用发布 `business_app_publication_55680b39cccf4dd9b3bd16be02bde14f`。

- `knowledge_list_bases` 成功，耗时 2413 毫秒。
- bug 库 `0191dcf1-3eae-5108-b6ef-f6a3df52aee1` 检索成功，返回 10 条；工具耗时 59134 毫秒。
- story 库 `72553438-2661-5964-8aac-5dbfa5190f3b` 检索成功，返回 10 条；工具耗时 94720 毫秒，超过原 SDK 默认 60 秒仍正常完成。
- 两次检索均通过当前 v3 离线内容输出合同校验；安全审计记录成功和返回计数，不导出具体命中正文。
- 本次全部 MCP 审计仅包含上述三次 Knowledge MCP 调用，没有 ONES 调用。验收时再次检查，ONES Mock 19121 端口仍不可达。
- Job 最终为 `SUCCEEDED`。结果 Outbox 为 `SUCCEEDED`、`attempt_count=1`；`dingtalk_stream_session_webhook` 投递成功，于 18:11:03 完成。

本次证明真实用户请求能够在 ONES 离线时取得知识检索结果并完成钉钉投递，不代表命中内容已通过人工相关性评测或能够证明现场根因。读取仅限安全审计元数据，未读取或导出原始业务消息、命中正文或凭据。

## 在线/离线配置补充验证

用户进一步确认：默认 online，命中须通过本人 ONES 实时可读性核验；显式 offline 才按平台 KB 授权读取。两种模式均返回快照片段，在线错误不自动降级。

- 增加 `KNOWLEDGE_ACCESS_MODE`，精确接受 online/offline；未设置默认 online，显式空值/非法值拒绝启动。主 Compose 使用仅对未设置值生效的默认表达式，`.env.example` 为 online；本机部署 `.env` 单独追加 offline，不读取其他配置值。
- 搜索 v4、目录 v3 合同；结果和安全审计携带实际 access_mode，模式不能由模型参数覆盖。模式在知识 MCP 启动时读取，同一工具合同支持两种模式，后续只切换模式无需重新发布。
- 模式与相关合同首批 190 项通过；在线和离线跨 300 秒的 Principal 续期及 Compose 默认值定向验证 3 项通过。
- 全知识回归：1249 passed、41 skipped、5 failed。失败定位为精简模型镜像的共享常量导入问题与两处启动/Compose 测试接线；修复后相关 71 项全部通过。共享常量已移入无依赖 knowledge_limits.py，真实 Embedding、Reranker、Runtime 镜像隔离导入均成功。
- 隔离真实 PostgreSQL/HTTP 容器两种模式均通过（2 passed，167.77 秒）：online 过滤 403 并在 500 整体失败；offline 在 ONES 403/500 下仍返回片段；两种模式的 KB 撤权、资源停用和重启行为通过。此处使用合成 ONES，不是实际生产 ONES 证明。
- Ruff、mypy、OpenSpec 严格校验、Markdown 链接、Compose config 和 diff 空白检查通过。
- 本次镜像基于已提交 HEAD `19358353` 加知识补丁构建，保留已提交的钉钉报告修复；不修改采集计划、数据、索引或角色权限。

配置版本本机部署与正式发布已完成：运行中的 Knowledge MCP 确认 access_mode=offline、搜索合同 v4；默认未配置的真实镜像确认模式 online。API、Worker、两个 Runtime、Knowledge MCP、ONES MCP 合同一致，模型服务与平台服务健康，knowledge-check ready 成功。Agent 修订 44（publication `agent_publication_ad7f2871adab4a7fafeda1f6b60d89b1`）、应用修订 59（publication `business_app_publication_7d1e6d54a32d44688f41b64302ee4bab`）、local 部署修订 33 已正常发布激活；知识库授权摘要未改变。临时验收容器已全部清理。

前节钉钉链路证据属于此前 v3 无配置版本，不冒充新增模式的真实 ONES 验收。本次按用户要求继续保持本机离线，没有接入真实 ONES；online 的权限与故障边界由合成双模式容器验证。
