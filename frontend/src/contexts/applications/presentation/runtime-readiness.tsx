import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  CircleOffIcon,
  CircleSlash2Icon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { RuntimeState } from "@/contexts/applications/domain/business-application"

const labels: Record<RuntimeState["runtime_status"], string> = {
  not_wired: "未接管",
  partially_wired: "部分接管",
  wired: "已接管",
  blocked: "已阻塞",
}

const componentLabels: Record<string, string> = {
  trigger_routing: "入口路由",
  agent_publication: "Agent 版本",
  session_policy: "会话策略",
  file_service: "File Service",
  file_worker: "File Worker",
  retention_policy: "数据保留策略",
  delivery: "结果投递",
  execution_policy: "执行策略",
  workflow: "工作流",
  capabilities: "API 能力",
}

const componentStatusLabels: Record<string, string> = {
  wired: "已接管",
  partially_wired: "部分接管",
  stored_only: "仅保存",
  unsupported: "暂不支持",
  blocked: "已阻塞",
}

export function RuntimeStatusBadge({
  state,
}: {
  state: Pick<RuntimeState, "runtime_status" | "reason_code">
}) {
  const Icon =
    state.runtime_status === "wired"
      ? CheckCircle2Icon
      : state.runtime_status === "partially_wired"
        ? AlertTriangleIcon
        : state.runtime_status === "blocked"
          ? CircleSlash2Icon
          : CircleOffIcon
  const className =
    state.runtime_status === "wired"
      ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100"
      : state.runtime_status === "partially_wired"
        ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
        : state.runtime_status === "blocked"
          ? "border-red-300 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100"
          : ""
  return (
    <Badge
      variant="outline"
      className={className}
      title={state.reason_code}
      aria-label={`运行状态：${labels[state.runtime_status]}`}
    >
      <Icon aria-hidden="true" />
      {labels[state.runtime_status]}
    </Badge>
  )
}

export function RuntimeReadinessPanel({
  state,
  compact = false,
}: {
  state: RuntimeState
  compact?: boolean
}) {
  const components = Object.entries(state.runtime_components)
  const runtimeComponents = components.filter(
    ([, component]) => component.impact === "runtime",
  )
  const governanceComponents = components.filter(
    ([, component]) => component.impact === "governance",
  )
  const content = (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <RuntimeStatusBadge state={state} />
        <span className="text-xs text-muted-foreground">
          当前运行环境：{state.runtime_environment || "未返回"}
        </span>
        {state.deployment_environment ? (
          <span className="text-xs text-muted-foreground">
            · 部署环境：{state.deployment_environment}
          </span>
        ) : null}
      </div>
      <div>
        <p className="text-sm font-medium">{state.message}</p>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {state.reason_code}
        </p>
      </div>
      {runtimeComponents.length ? (
        <dl className="grid gap-2 sm:grid-cols-2">
          {runtimeComponents.map(([name, component]) => (
            <div key={name} className="rounded-md border bg-muted/20 p-3">
              <dt className="flex items-center justify-between gap-2 text-xs font-medium">
                <span>{componentLabels[name] ?? name}</span>
                <span className="font-mono text-[10px] text-muted-foreground uppercase">
                  {componentStatusLabels[component.status] ?? component.status}
                </span>
              </dt>
              <dd className="mt-1 text-xs leading-5 text-muted-foreground">
                {component.message}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-xs text-muted-foreground">
          服务端未返回组件状态；界面不会据此推断为已接管。
        </p>
      )}
      {governanceComponents.length ? (
        <div>
          <p className="text-xs font-medium">治理提示（不影响运行接管）</p>
          <dl className="mt-2 grid gap-2 sm:grid-cols-2">
            {governanceComponents.map(([name, component]) => (
              <div key={name} className="rounded-md border border-dashed p-3">
                <dt className="flex items-center justify-between gap-2 text-xs font-medium">
                  <span>{componentLabels[name] ?? name}</span>
                  <span className="font-mono text-[10px] text-muted-foreground uppercase">
                    {componentStatusLabels[component.status] ?? component.status}
                  </span>
                </dt>
                <dd className="mt-1 text-xs leading-5 text-muted-foreground">
                  {component.message}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
      {state.affected_routes.length ? (
        <div>
          <p className="text-xs font-medium">受影响入口</p>
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {state.affected_routes.map((route, index) => (
              <li
                key={`${route.trigger_type}-${route.connector_id}-${index}`}
                className="rounded border px-2 py-1.5"
              >
                {route.trigger_type} · {route.connector_id} ·{" "}
                <span className="font-mono">{route.routing_key_summary}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
  if (compact) return content
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>运行时就绪状态</CardTitle>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  )
}

export function RuntimeOperationImpact({
  action,
}: {
  state: RuntimeState
  action: "activate" | "rollback" | "deactivate"
  targetEnvironment: string
}) {
  const text =
    action === "deactivate"
      ? "停用后释放上述入口；后续未命中消息将返回配置错误且不创建任务。已入队任务继续使用原固定版本。"
      : `${action === "rollback" ? "回退" : "激活"}后由该发布版本接管匹配入口；未命中消息将返回配置错误且不创建任务，已入队任务不切换版本。`
  return (
    <div
      className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs leading-5 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100"
      role="status"
    >
      {text}
    </div>
  )
}
