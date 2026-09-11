# ONES 更新缺陷：钉钉 Stream 来源误拒修复

日期：2026-09-11

## 请求与根因

用户明确要求“改写描述”调用 ONES MCP 更新缺陷接口，并保留外部操作确认。

实际入站适配器 `DingTalkStreamMessageService.to_channel_event` 产生 `source.type=dingding_stream`，入站服务将其保存为 Job 的 `source_channel`。`OnesPrincipalResolver.resolve_confirmation_route` 原来只接受 `dingtalk`、`dingding`，因此会在创建确认 Intent 前把有效钉钉 Stream 私聊和群聊误拒为 `ones_mutation_dingtalk_source_required`。

这是已通过代码和本地回归复现的来源识别缺陷，不是 ONES Provider 写接口失败。因当前服务停止，本次没有读取真实失败 Job，也没有声称已核实某个真实 Job 的全部授权事实。

## 修复边界

- 在共用 ONES 确认路由中接受 `dingding_stream`，兼容原有两个来源值。
- 保留 Job/Session 来源 Connector 一致、Connector 类型与启用/入站状态、企业 ACTIVE、私聊/群聊会话和企业内唯一原操作人身份校验。
- Web、后台及未声明的来源仍拒绝；不以工具参数代替服务端可信来源事实。
- 描述更新仍调用 `ones_update_task(uuid, description)`，先读取当前缺陷、生成差异和待确认 Intent；确认前不调用 ONES 更新接口，也不修改其它字段。
- 没有修改工具 schema、Provider 合同、授权范围、数据库结构、确认要求或发布版本。
- 共用此路由的缺陷创建保留原有行为；未扩展其它 ONES 写入能力。

## 本地验证

1. 新来源回归在修复前：6 failed / 15 passed，失败包括 Stream 私聊/群聊和实际 adapter → 更新工具准备流程。
2. 修复后同一组：21 passed。
3. 更新、创建、身份架构、钉钉 Stream 入站套件：140 passed。
4. ONES MCP runtime 与外部 I/O 事务边界套件：49 passed。
5. `ruff check`（修改的 Python 文件）、带 `MYPYPATH=backend` 的目标 `mypy --follow-imports=silent`、`docker compose config --quiet`、`git diff --check` 通过。
6. `openspec validate add-governed-ones-task-update --strict` 通过。
7. `docker compose build ones-mcp` 成功。镜像：`sha256:bd588fbc049e2e2f126251dcc81ca3129c82c2b187b4b7f6139983870be4f314`。
8. 对上述固定镜像执行只读文件系统、`--network none` 的独立 smoke：应用 import 与 10 组来源/会话确认路由校验通过，没有挂载运行环境或调用 Provider。

本地组件测试使用实际 Stream adapter 和实际确认路由，但数据库、Provider、Action Intent 准备使用测试替身；验证了只保存描述 Patch、确认目标为原操作人、返回 `confirmation_required`，且准备阶段 ONES 更新次数为 0。此证据不等于真实模型编排、卡片投递、点击或 ONES 更新成功。

最初未配置 `MYPYPATH` 的单文件 mypy 因无法正确解析项目 `app` 包出现 Any 相关错误；使用项目 backend 路径重跑目标检查后通过，不将最初结果误记为既有代码缺陷。

## 部署与剩余验收

检查时本项目所有 Compose 容器已停止约 10 小时，包括 `ones-mcp`、钉钉入站服务和 external-action-worker。本次只重建镜像，没有启动服务、重建现存停止容器、运行迁移、修改发布授权或处理积压任务。因此新镜像尚未进入服务运行态，不能声称已上线恢复。

恢复正常服务时，应使用新镜像重建/启动 `ones-mcp`（例如在依赖服务恢复后执行 `docker compose up -d --no-deps ones-mcp`），而不是只对旧容器执行 `docker compose start`。这次未改工具 schema；已授权并发布 `ones_update_task` 的 Agent/Application 无需仅为此修复重新发布。

随后通过钉钉发送原描述更新请求，验证 `ones_update_task` → 新确认卡 → 原用户确认 → ONES 执行及只读回查。不得复用过期 Intent，也不得把准备成功视为已更新。本次没有真实调用 ONES、发送卡片或修改用户缺陷；原任务 7.4、7.5 真实验收保持未完成。
