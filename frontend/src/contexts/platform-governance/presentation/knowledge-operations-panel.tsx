import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog"
import { KnowledgeError, KnowledgeField } from "./knowledge-resource-ui"
import { KnowledgePlanForm } from "./knowledge-plan-form"
import {
  useKnowledgeOperationEvents,
  useKnowledgeOperationsCommand,
} from "../application/knowledge-operations-query"
import {
  displayTime,
  buildStepLines,
  vectorProgressSummary,
  operationNames,
  phaseNames,
  serviceNames,
  type KnowledgeOperationsSnapshot,
  type KnowledgePlan,
  type OperationRequest,
} from "../domain/knowledge-operations"

export function KnowledgeOperationsPanel({
  data,
  error,
  canManage,
  onRefresh,
}: {
  data?: KnowledgeOperationsSnapshot
  error: unknown
  canManage: boolean
  onRefresh: () => void
}) {
  const command = useKnowledgeOperationsCommand()
  const [confirmation, setConfirmation] = useState<OperationRequest | null>(
    null
  )
  const [backfill, setBackfill] = useState<KnowledgePlan | null>(null)
  const [dates, setDates] = useState({ first: "", last: "" })
  const [logs, setLogs] = useState<{ operationId: string | null } | null>(null)
  const [service, setService] = useState("")
  const [creating, setCreating] = useState(false)
  const [editingPlan, setEditingPlan] = useState<string | undefined>()
  const [notice, setNotice] = useState("")
  const events = useKnowledgeOperationEvents(
    logs?.operationId ?? null,
    service,
    logs !== null
  )
  const deployBusy = data?.operations.some(
    (o) =>
      !o.binding_id && ["QUEUED", "RUNNING", "RETRY_WAIT"].includes(o.state)
  )
  function ask(kind: OperationRequest["kind"], plan?: KnowledgePlan) {
    command.reset()
    setConfirmation({
      kind,
      request_key: crypto.randomUUID(),
      ...(plan ? { binding_id: plan.id } : {}),
    })
  }
  async function execute() {
    if (!confirmation) return
    try {
      const result = await command.mutateAsync({
        action: "submit",
        input: confirmation,
      })
      setConfirmation(null)
      setBackfill(null)
      setNotice("任务已提交，可在任务记录中查看进度。关闭页面不影响执行。")
      if ("kind" in result) setLogs({ operationId: result.id })
    } catch {
      /* 保留相同幂等键，响应丢失时可安全重试。 */
    }
  }
  async function schedule(plan: KnowledgePlan) {
    try {
      await command.mutateAsync({
        action: "schedule",
        id: plan.id,
        revision: plan.revision,
        enabled: !(plan.enabled && plan.schedule_enabled),
      })
    } catch {
      /* 展示错误 */
    }
  }
  return (
    <section
      className="grid gap-5"
      aria-label="知识库运维"
      data-testid="knowledge-operations"
    >
      <KnowledgeError error={error} />
      <KnowledgeError error={confirmation ? null : command.error} />
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      <div className="rounded-xl border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">知识库服务</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              三个知识库共享部署服务；停止服务会影响它们的在线检索。
            </p>
          </div>
          <span role="status" className="text-sm">
            运维执行器：
            {data
              ? data.controller.online
                ? "在线"
                : "未连接，状态待核实"
              : "正在读取…"}
          </span>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          运行版本：{data?.deployment.snapshot.running_version ?? "尚未确认"} ·
          已构建版本：{data?.deployment.snapshot.built_version ?? "尚未构建"}
        </p>
        <div className="my-4 grid gap-2 sm:grid-cols-3">
          {Object.entries(serviceNames)
            .filter(
              ([name]) =>
                name.startsWith("knowledge-") && !name.endsWith("prepare")
            )
            .map(([name, label]) => {
              const current = data?.controller.snapshot.services?.find(
                (s) => s.name === name
              )
              const status = !data?.controller.online
                ? "未知"
                : current
                  ? (phaseNames[current.state] ?? "未知")
                  : "未知"
              return (
                <div
                  key={name}
                  className="rounded-md bg-muted/40 px-3 py-2 text-sm"
                >
                  {label}：{status}
                  {current?.state === "running" &&
                  data?.controller.online &&
                  current.health !== "none"
                    ? ` · ${phaseNames[current.health] ?? "检查中"}`
                    : ""}
                </div>
              )
            })}
        </div>
        {data?.controller.snapshot.error_code && (
          <p role="alert" className="mb-3 text-sm">
            无法读取服务状态：{data.controller.snapshot.error_code}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {canManage &&
            (["build", "up", "stop"] as const).map((kind) => (
              <Button
                key={kind}
                variant={kind === "up" ? "default" : "outline"}
                disabled={
                  !data?.controller.online ||
                  deployBusy ||
                  command.isPending ||
                  (kind === "up" && !data.deployment.snapshot.built_version)
                }
                onClick={() => ask(kind)}
              >
                {operationNames[kind]}
              </Button>
            ))}
          <Button
            variant="outline"
            onClick={() => {
              setService("")
              setLogs({ operationId: null })
            }}
          >
            查看统一日志
          </Button>
          <Button variant="outline" onClick={onRefresh}>
            刷新状态
          </Button>
        </div>
        {!data?.controller.online && (
          <p className="mt-3 text-sm text-muted-foreground">
            首次使用需由运维安装常驻执行器。已有知识资源仍可管理；此处不会推断知识服务已停止。
          </p>
        )}
      </div>
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">采集计划</h2>
        {canManage && (
          <Button
            variant="outline"
            onClick={() => {
              setEditingPlan(undefined)
              setCreating(true)
            }}
          >
            新建采集计划
          </Button>
        )}
      </div>
      {data?.plans.length === 0 && (
        <p className="text-sm text-muted-foreground">
          尚未配置采集计划。已有知识库不会因发布而自动开启采集。
        </p>
      )}
      {data?.plans.map((plan) => {
        const syncRunning = data.operations.some(
          (o) => o.binding_id === plan.id && o.state === "RUNNING"
        )
        const activeOperation = data.operations.find(
          (o) =>
            o.binding_id === plan.id &&
            ["QUEUED", "RUNNING", "RETRY_WAIT"].includes(o.state)
        )
        return (
          <article
            key={plan.id}
            id={`knowledge-plan-${plan.id}`}
            className="grid gap-3 rounded-xl border p-5"
          >
            <div className="flex flex-wrap justify-between gap-2">
              <h3 className="font-medium">{plan.code}</h3>
              <span className="text-sm">
                {!plan.enabled
                  ? "采集未启用"
                  : plan.schedule_enabled
                    ? "自动同步已开启"
                    : "自动同步已暂停"}
              </span>
            </div>
            <p className="text-sm">
              目标知识库：{plan.bases.map((b) => b.code).join("、")}
            </p>
            <p className="text-xs text-muted-foreground">
              每 {plan.interval_seconds / 3600} 小时执行 · 最近成功：
              {displayTime(plan.last_success_at)} · 下次执行：
              {plan.enabled && plan.schedule_enabled && syncRunning
                ? `本轮完成后 ${plan.interval_seconds / 3600} 小时`
                : displayTime(plan.next_run_at)}
            </p>
            {activeOperation && (
              <p className="text-sm">
                当前任务：{operationNames[activeOperation.kind]} ·{" "}
                {data.sync_worker.online
                  ? phaseNames[activeOperation.state]
                  : "同步进程未连接，等待恢复"}
              </p>
            )}
            {plan.run && (
              <div
                className="grid gap-1 text-sm"
                aria-label={`${plan.code} 同步进度`}
              >
                <p>
                  最近运行：{phaseNames[plan.run.phase] ?? plan.run.phase} ·
                  更新于 {displayTime(plan.run.updated_at)}
                </p>
                {plan.run.collection && (
                  <p>
                    采集日期：{plan.run.collection.first_day} 至{" "}
                    {plan.run.collection.last_day} · 已完成{" "}
                    {plan.run.collection.completed_days} /{" "}
                    {plan.run.collection.total_days} 天
                  </p>
                )}
                {plan.run.documents && (
                  <p>
                    文档处理：已完成 {plan.run.documents.completed} /{" "}
                    {plan.run.documents.total} 条 · 失败{" "}
                    {plan.run.documents.failed} 条
                  </p>
                )}
                {plan.run.progress && (
                  <p>
                    当前文档向量处理：
                    {vectorProgressSummary(plan.run.progress)}
                  </p>
                )}
                {plan.run.error_code && (
                  <p role="alert">
                    {plan.run.error_code}
                    ；已完成内容保持可用，请在任务记录查看并重试。
                  </p>
                )}
              </div>
            )}
            {canManage && (
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  disabled={!plan.enabled || command.isPending}
                  onClick={() => ask("sync", plan)}
                >
                  立即同步
                </Button>
                <Button
                  variant="outline"
                  disabled={
                    !plan.enabled || !plan.last_success_at || command.isPending
                  }
                  onClick={() => {
                    setDates({ first: "", last: "" })
                    setBackfill(plan)
                  }}
                >
                  日期补采
                </Button>
                <Button
                  variant="outline"
                  disabled={command.isPending}
                  onClick={() => void schedule(plan)}
                >
                  {plan.enabled && plan.schedule_enabled
                    ? "暂停自动同步"
                    : "开启自动同步"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    setEditingPlan(plan.id)
                    setCreating(true)
                  }}
                >
                  采集配置
                </Button>
              </div>
            )}
          </article>
        )
      })}
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-left text-sm">
          <caption className="p-4 text-left font-semibold">
            最近任务 · 关闭页面后继续执行
          </caption>
          <thead className="bg-muted/40">
            <tr>
              {["任务", "范围", "状态与阶段", "提交时间", "操作"].map((s) => (
                <th key={s} className="p-3">
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data?.operations.map((op) => (
              <tr key={op.id} className="border-t">
                <td className="p-3">{operationNames[op.kind]}</td>
                <td className="p-3">
                  {op.binding_id
                    ? (data.plans.find((p) => p.id === op.binding_id)?.code ??
                      "采集计划")
                    : "整套知识服务"}
                  {op.parameters.first_day && (
                    <p className="text-xs">
                      {op.parameters.first_day} 至 {op.parameters.last_day}
                    </p>
                  )}
                </td>
                <td className="p-3">
                  {op.state === "RUNNING" &&
                  !(op.binding_id
                    ? data.sync_worker.online
                    : data.controller.online)
                    ? "执行状态待核实"
                    : phaseNames[op.state]}{" "}
                  · {phaseNames[op.stage] ?? op.stage}
                  {op.error_code && <p className="text-xs">{op.error_code}</p>}
                </td>
                <td className="p-3">{displayTime(op.created_at)}</td>
                <td className="p-3">
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      onClick={() => {
                        setService("")
                        setLogs({ operationId: op.id })
                      }}
                    >
                      查看进度
                    </Button>
                    {canManage &&
                      ["FAILED", "PARTIAL", "INTERRUPTED"].includes(
                        op.state
                      ) && (
                        <Button
                          variant="outline"
                          disabled={command.isPending}
                          onClick={() =>
                            void command
                              .mutateAsync({ action: "retry", id: op.id })
                              .catch(() => {})
                          }
                        >
                          重试
                        </Button>
                      )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.operations.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">暂无运维任务。</p>
        )}
      </div>
      <Sheet open={creating} onOpenChange={setCreating}>
        <SheetContent className="overflow-y-auto sm:max-w-2xl">
          <SheetHeader>
            <SheetTitle>配置采集计划</SheetTitle>
            <SheetDescription>
              配置来源与三个知识库的映射。保存不会自动发布或授权。
            </SheetDescription>
          </SheetHeader>
          <KnowledgePlanForm
            key={editingPlan ?? "new"}
            bindingId={editingPlan}
            onClose={() => setCreating(false)}
          />
        </SheetContent>
      </Sheet>
      <Sheet
        open={backfill !== null}
        onOpenChange={(open) => {
          if (!open) setBackfill(null)
        }}
      >
        <SheetContent>
          <SheetHeader>
            <SheetTitle>指定日期补采</SheetTitle>
            <SheetDescription>
              按北京时间的单据创建日期补采，包含起止日期。范围：
              {backfill?.bases.map((b) => b.code).join("、")}
              。当前任务完成后执行。
            </SheetDescription>
          </SheetHeader>
          <form
            className="grid gap-4 p-5"
            onSubmit={(e) => {
              e.preventDefault()
              if (
                backfill &&
                dates.first &&
                dates.last &&
                dates.first <= dates.last
              )
                setConfirmation({
                  kind: "backfill",
                  request_key: crypto.randomUUID(),
                  binding_id: backfill.id,
                  first_day: dates.first,
                  last_day: dates.last,
                })
            }}
          >
            <KnowledgeField label="起始日期">
              <Input
                aria-label="起始日期"
                type="date"
                required
                min={backfill?.first_day ?? undefined}
                max={dates.last || undefined}
                value={dates.first}
                onChange={(e) => setDates({ ...dates, first: e.target.value })}
              />
            </KnowledgeField>
            <KnowledgeField label="结束日期">
              <Input
                aria-label="结束日期"
                type="date"
                required
                min={dates.first || backfill?.first_day || undefined}
                value={dates.last}
                onChange={(e) => setDates({ ...dates, last: e.target.value })}
              />
            </KnowledgeField>
            <Button
              type="submit"
              disabled={!dates.first || !dates.last || dates.first > dates.last}
            >
              提交补采
            </Button>
          </form>
        </SheetContent>
      </Sheet>
      <AlertDialog
        open={confirmation !== null}
        onOpenChange={(open) => {
          if (!open && !command.isPending) setConfirmation(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirmation && operationNames[confirmation.kind]}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmation?.kind === "stop"
                ? "将停止整套知识库服务，所有知识库暂时无法在线检索。采集断点、数据和模型保留，主程序及运维执行器继续运行。"
                : confirmation?.kind === "build"
                  ? "构建当前服务器已安装版本的知识镜像。完成后可应用新版本，构建本身不会切换运行服务。"
                  : confirmation?.kind === "up"
                    ? "检查依赖并应用最后成功构建的版本；恢复未完成任务，按各计划开关进行同步。应用版本期间检索可能暂时不可用。"
                    : `任务将作用于该采集计划下的全部知识库，等待同来源活动任务完成后执行。${confirmation?.first_day ? `补采范围：${confirmation.first_day} 至 ${confirmation.last_day}。` : ""}`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <KnowledgeError error={command.error} />
          <AlertDialogFooter>
            <AlertDialogCancel disabled={command.isPending}>
              取消
            </AlertDialogCancel>
            <Button disabled={command.isPending} onClick={() => void execute()}>
              确认执行
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Sheet
        open={logs !== null}
        onOpenChange={(open) => {
          if (!open) setLogs(null)
        }}
      >
        <SheetContent className="overflow-y-auto sm:max-w-2xl">
          <SheetHeader>
            <SheetTitle>
              {logs?.operationId ? "任务进度与日志" : "统一运维日志"}
            </SheetTitle>
            <SheetDescription>
              自动刷新最近 200
              条安全事件；不展示凭据或业务正文。时间均为北京时间。
            </SheetDescription>
          </SheetHeader>
          <div className="grid gap-3 p-5">
            <select
              className="rounded border p-2"
              aria-label="筛选日志服务"
              value={service}
              onChange={(e) => setService(e.target.value)}
            >
              <option value="">全部服务</option>
              {Object.entries(serviceNames).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
            <KnowledgeError error={events.error} />
            {events.isPending && <p>正在读取事件…</p>}
            {events.data?.events.length === 0 && (
              <p>暂无事件，任务可能仍在排队。</p>
            )}
            <ol className="grid gap-3">
              {events.data?.events.map((event) => (
                <li key={event.id} className="rounded border p-3 text-sm">
                  <p className="text-xs text-muted-foreground">
                    {displayTime(event.created_at)} ·{" "}
                    {serviceNames[event.service] ?? event.service}
                  </p>
                  <p>{phaseNames[event.code] ?? event.code}</p>
                  {event.code === "build_step"
                    ? buildStepLines(event.details).map((line) => (
                        <p key={line} className="text-xs break-all">
                          {line}
                        </p>
                      ))
                    : Object.entries(event.details).map(([key, value]) => (
                        <p key={key} className="text-xs break-all">
                          {key}：{value}
                        </p>
                      ))}
                </li>
              ))}
            </ol>
          </div>
        </SheetContent>
      </Sheet>
    </section>
  )
}
