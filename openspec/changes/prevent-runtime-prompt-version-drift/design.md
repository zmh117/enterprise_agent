## Context

用户报告生产请求 v8 与 Runtime v10 不一致。本地只读核对得到两个 Worker 和两个 Runtime 均为 v10，checkout 为 v11；未访问生产服务器，无法区分生产旧 Worker 与升级前冻结请求。代码已共享版本常量，但不同镜像里的常量仍会不同。

## Goals / Non-Goals

**Goals:** 新执行前发现错配；在就绪信息展示安全版本差异；保留调用身份、严格工具契约与恢复语义。

**Non-Goals:** 不改 Prompt 内容、不接受任意版本、不迁移冻结请求、不自动重跑 Job、不部署或重启服务。

## Decisions

1. `/version` 和 `/ready` 均从共享常量返回 `prompt_template_version`。被动探针默认与调用方当前版本核对；两个响应不一致、缺失或非法均不就绪。对外只投影固定格式的版本或固定占位文字。
2. 池准入探针对 PREPARED 使用冻结请求的模板版本；RUNNING/TERMINAL 恢复不检查当前 Prompt 版本，因为重放的是持久事件，不产生新的 Prompt。构建身份、节点身份和旧事件 hash/版本校验保持。
3. Registry 在恢复分支之后、新调用占槽和 admit 之前比较请求与自身常量。拒绝用 `runtime_prompt_version_mismatch`，传输层映射为不可重试的部署错误，正文不回显请求值。这样旧 Worker 也不会越过新版 Runtime 的防线。
4. 保持现有有界准入等待，不新建升级调度器或变更 Job 状态。运维说明要求所有副本同一发布物、真实 build identity；不可用通用 local-dev 证明组件一致。

## Risks / Trade-offs

- 旧 Runtime 不声明版本 → 新探针将其排除新执行，必须协调升级，不能以缺字段作为匹配。
- 本地测试不代表生产恢复 → 验收报告区分合成回归、本机只读版本核对、生产尚未验收。
- 生产某请求可能已冻结旧版本 → 先判断 PREPARED/已执行/终态，不改写 digest 或绕过未知结果保护。

## Migration Plan

无需迁移。按部署流程将 API、所有 Worker、Runtime 及要求同构建身份的 MCP 组件使用同一发布物更新；在恢复入口验收已有终态不触发新模型调用。回滚也以成套组件为单位。
