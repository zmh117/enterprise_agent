import {
  ActivityIcon,
  ArrowLeftIcon,
  MessagesSquareIcon,
  RefreshCwIcon,
  ServerIcon,
  TruckIcon,
} from "lucide-react"
import { Link, useParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  useConversation,
  useRuntimeJob,
  useRuntimeJobs,
} from "@/contexts/operations/application/runtime-record-queries"
import type {
  DeliveryAttempt,
  DeliveryChunk,
  DeliveryEvent,
  McpToolCall,
  RuntimeJob,
  RuntimeJobDetail,
} from "@/contexts/operations/domain/runtime-record"
import { ApiError } from "@/shared/api/api-client"

export function RuntimeRecordsPage() {
  const query = useRuntimeJobs()
  return (
    <PageFrame>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-indigo-700">
            <ActivityIcon className="size-4" aria-hidden="true" />
            本人历史
          </div>
          <h1 className="mt-2 text-2xl font-semibold">Agent Job</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            只展示当前系统用户自己的任务、MCP 调用与结果投递状态。
          </p>
        </div>
        <Button variant="outline" onClick={() => void query.refetch()} disabled={query.isFetching}>
          <RefreshCwIcon className={query.isFetching ? "animate-spin" : ""} />
          刷新
        </Button>
      </header>
      {query.isLoading ? <Skeleton className="h-72 w-full" /> : null}
      <ErrorState error={query.error} retry={() => void query.refetch()} />
      {query.data ? (
        <Card className="shadow-none">
          <CardContent className="divide-y p-0">
            {query.data.map((job) => <JobRow key={job.id} job={job} />)}
            {!query.data.length ? (
              <p className="p-8 text-center text-sm text-muted-foreground">暂无本人任务。</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </PageFrame>
  )
}

export function JobRow({
  job,
  detailBase = "/operations/jobs",
}: {
  job: RuntimeJob
  detailBase?: string
}) {
  return (
    <article className="grid gap-3 p-4 text-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0">
        <Link to={`${detailBase}/${encodeURIComponent(job.id)}`} className="font-mono text-xs font-medium hover:underline">
          {job.id}
        </Link>
        <p className="mt-1 text-xs text-muted-foreground">
          {job.source_channel || "unknown"} · {job.agent_code} · {formatDate(job.created_at)}
        </p>
        {job.correlation_id ? <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{job.correlation_id}</p> : null}
      </div>
      <Badge variant="secondary">{jobStatusLabel(job.status)}</Badge>
    </article>
  )
}

export function RuntimeJobDetailPage() {
  const jobId = useParams().jobId ?? ""
  const query = useRuntimeJob(jobId)
  if (query.isLoading) return <PageSkeleton />
  if (query.isError || !query.data) return <PageFrame><PageBack href="/operations/jobs" label="返回本人 Job 历史" /><ErrorState error={query.error} retry={() => void query.refetch()} /></PageFrame>
  return (
    <RuntimeJobEvidenceView
      evidence={query.data}
      backHref="/operations/jobs"
      backLabel="返回本人 Job 历史"
      conversationHref={`/operations/conversations/${encodeURIComponent(query.data.job.session_id)}`}
    />
  )
}

export function RuntimeJobEvidenceView({
  evidence,
  backHref,
  backLabel,
  conversationHref,
  action,
}: {
  evidence: RuntimeJobDetail
  backHref: string
  backLabel: string
  conversationHref?: string
  action?: React.ReactNode
}) {
  const { job } = evidence
  return (
    <PageFrame>
      <PageBack href={backHref} label={backLabel} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Job 运行证据</h1>
          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{job.id}</p>
        </div>
        {action}
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <FactCard title="执行" rows={[
          ["状态", jobStatusLabel(job.status)],
          ["Agent", job.agent_code],
          ["来源", job.source_channel || "—"],
          ["关联 ID", job.correlation_id || "—"],
          ["创建", formatDate(job.created_at)],
          ["结束", formatDate(job.finished_at)],
        ]} />
        <FactCard title="边界" rows={[
          ["MCP Tool 调用数", String(evidence.mcp_tool_calls.length)],
          ["执行策略调用计数", String(job.tool_call_count)],
          ["策略耗尽", job.execution_policy_exhausted ? "是" : "否"],
          ["错误分类", job.last_error_code || "—"],
          ["安全错误摘要", job.error_summary || "—"],
        ]} />
      </div>
      <McpTimeline calls={evidence.mcp_tool_calls} />
      <StepTimeline steps={evidence.steps} dispatch={evidence.dispatch} />
      <DeliveryTimeline
        events={evidence.deliveries.events}
        attempts={evidence.deliveries.attempts}
        chunks={evidence.deliveries.chunks}
      />
      {conversationHref ? <Card className="shadow-none">
        <CardHeader><CardTitle className="flex items-center gap-2"><MessagesSquareIcon className="size-4" />会话</CardTitle></CardHeader>
        <CardContent>
          <Link className={buttonVariants({ variant: "outline" })} to={conversationHref}>
            查看本人会话
          </Link>
        </CardContent>
      </Card> : null}
    </PageFrame>
  )
}

function McpTimeline({ calls }: { calls: McpToolCall[] }) {
  return (
    <Card className="mt-4 shadow-none">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ServerIcon className="size-4" />MCP Tool Call</CardTitle>
        <p className="text-sm text-muted-foreground">只展示脱敏摘要、固定版本和哈希，不展示 Token、连接信息或原始响应。</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {calls.map((call) => (
          <article key={call.id} className="rounded-lg border p-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{call.mcp_server_code}@{call.server_version}</Badge>
              <span className="font-mono text-xs font-medium">{call.tool_name}</span>
              <Badge variant={call.status === "SUCCEEDED" ? "secondary" : "destructive"}>{call.status}</Badge>
            </div>
            <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-3">
              <Fact label="Tool Schema Hash" value={call.tool_schema_hash} mono />
              <Fact label="Resource Revision" value={call.resource_revision_id || "不适用"} mono />
              <Fact label="Credential Revision" value={call.credential_revision ? `r${call.credential_revision}` : "不适用"} />
              <Fact label="Subject Snapshot" value={call.subject_snapshot_id || "不适用"} mono />
              <Fact label="Result Hash / Size" value={`${call.result_hash || "—"} / ${call.result_size} B`} mono />
              <Fact label="耗时 / Correlation" value={`${call.duration_ms} ms / ${call.correlation_id}`} mono />
            </dl>
            <details className="mt-3 rounded border bg-muted/20 px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium">脱敏请求摘要与 attempts</summary>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">{JSON.stringify({ request_summary: call.request_summary, attempts: call.attempts }, null, 2)}</pre>
            </details>
          </article>
        ))}
        {!calls.length ? <p className="text-sm text-muted-foreground">此 Job 没有 MCP Tool Call。</p> : null}
      </CardContent>
    </Card>
  )
}

function StepTimeline({ steps, dispatch }: { steps: Array<Record<string, unknown>>; dispatch: Record<string, unknown> | null }) {
  return (
    <div className="my-4 grid gap-4 lg:grid-cols-2">
      <Card className="shadow-none"><CardHeader><CardTitle>执行步骤</CardTitle></CardHeader><CardContent>
        {steps.length ? <ol className="space-y-3">{steps.map((step, index) => <TimelineItem key={String(step.id ?? index)} label={String(step.title ?? step.step_type ?? "步骤")} value={String(step.content ?? "")} />)}</ol> : <p className="text-sm text-muted-foreground">暂无步骤。</p>}
      </CardContent></Card>
      <Card className="shadow-none"><CardHeader><CardTitle>Dispatch</CardTitle></CardHeader><CardContent>
        {dispatch ? <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">{JSON.stringify(dispatch, null, 2)}</pre> : <p className="text-sm text-muted-foreground">暂无 Dispatch 记录。</p>}
      </CardContent></Card>
    </div>
  )
}

function DeliveryTimeline({ events, attempts, chunks }: { events: DeliveryEvent[]; attempts: DeliveryAttempt[]; chunks: DeliveryChunk[] }) {
  return (
    <Card className="mb-4 shadow-none">
      <CardHeader><CardTitle className="flex items-center gap-2"><TruckIcon className="size-4" />投递</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {events.map((event) => (
          <article key={event.id} className="rounded-lg border p-4 text-sm">
            <div className="flex flex-wrap gap-2"><Badge variant="outline">{event.route_type}</Badge><Badge variant="secondary">{event.status}</Badge></div>
            <p className="mt-2 text-xs text-muted-foreground">尝试 {event.attempt_count} · 创建 {formatDate(event.created_at)}</p>
            {event.last_error_code ? <p className="mt-2 text-xs text-destructive">{event.last_error_code} · {event.last_error_summary}</p> : null}
            <p className="mt-2 text-xs text-muted-foreground">attempts {attempts.filter((item) => item.delivery_outbox_id === event.id).length} · chunks {chunks.filter((item) => item.delivery_outbox_id === event.id).length}</p>
          </article>
        ))}
        {!events.length ? <p className="text-sm text-muted-foreground">此 Job 没有投递事件。</p> : null}
      </CardContent>
    </Card>
  )
}

export function ConversationDetailPage() {
  const sessionId = useParams().sessionId ?? ""
  const query = useConversation(sessionId)
  if (query.isLoading) return <PageSkeleton />
  if (query.isError || !query.data) return <PageFrame><PageBack href="/operations/jobs" label="返回本人 Job 历史" /><ErrorState error={query.error} retry={() => void query.refetch()} /></PageFrame>
  return (
    <PageFrame>
      <PageBack href="/operations/jobs" label="返回本人 Job 历史" />
      <h1 className="text-2xl font-semibold">本人会话</h1>
      <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{query.data.session.id}</p>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <Card className="shadow-none"><CardHeader><CardTitle>消息</CardTitle></CardHeader><CardContent className="space-y-3">
          {query.data.messages.map((message, index) => <article key={String(message.id ?? index)} className="rounded-lg border p-3 text-sm"><p className="text-xs font-medium text-muted-foreground">{String(message.role ?? message.message_type ?? "message")}</p><p className="mt-1 whitespace-pre-wrap">{String(message.content ?? message.content_text ?? "")}</p></article>)}
          {!query.data.messages.length ? <p className="text-sm text-muted-foreground">暂无消息。</p> : null}
        </CardContent></Card>
        <Card className="shadow-none"><CardHeader><CardTitle>同会话 Job</CardTitle></CardHeader><CardContent className="space-y-3">
          {query.data.jobs.map((job) => <JobRow key={job.id} job={job} />)}
        </CardContent></Card>
      </div>
    </PageFrame>
  )
}

function FactCard({ title, rows }: { title: string; rows: Array<[string, string]> }) {
  return <Card className="shadow-none"><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent><dl className="grid gap-3 text-sm sm:grid-cols-[9rem_1fr]">{rows.map(([label, value]) => <div key={label} className="contents"><dt className="text-muted-foreground">{label}</dt><dd className="break-all">{value}</dd></div>)}</dl></CardContent></Card>
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div><dt className="text-muted-foreground">{label}</dt><dd className={`mt-0.5 break-all ${mono ? "font-mono" : ""}`}>{value}</dd></div>
}

function TimelineItem({ label, value }: { label: string; value: string }) {
  return <li className="border-l-2 pl-3"><p className="text-sm font-medium">{label}</p><p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">{value || "无摘要"}</p></li>
}

export function RuntimeErrorState({ error, retry }: { error: unknown; retry: () => void }) {
  if (!error) return null
  return <Card className="border-destructive/30 shadow-none"><CardContent className="flex flex-wrap items-center justify-between gap-3 p-4"><p role="alert" className="text-sm text-destructive">{error instanceof ApiError ? error.message : "请求失败，请稍后重试。"}</p><Button size="sm" variant="outline" onClick={retry}>重试</Button></CardContent></Card>
}

function ErrorState({ error, retry }: { error: unknown; retry: () => void }) {
  return <RuntimeErrorState error={error} retry={retry} />
}

function PageBack({ href, label }: { href: string; label: string }) {
  return <Link to={href} className={`${buttonVariants({ variant: "ghost", size: "sm" })} mb-4`}><ArrowLeftIcon />{label}</Link>
}

export function RuntimePageFrame({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto w-full max-w-[1400px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return <RuntimePageFrame>{children}</RuntimePageFrame>
}

function PageSkeleton() {
  return <PageFrame><Skeleton className="h-8 w-72" /><Skeleton className="h-80 w-full" /></PageFrame>
}

function jobStatusLabel(status: string) {
  return ({ PENDING: "等待中", RUNNING: "运行中", SUCCEEDED: "成功", FAILED: "失败", TIMEOUT: "超时", CANCELLED: "已取消" } as Record<string, string>)[status] ?? status
}

function formatDate(value?: string | null) {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN")
}
