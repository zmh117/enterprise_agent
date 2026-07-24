import {
  ActivityIcon,
  ArrowLeftIcon,
  MessagesSquareIcon,
  RefreshCwIcon,
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
import type { RuntimeJob } from "@/contexts/operations/domain/runtime-record"
import { ApplicationState } from "@/contexts/applications/presentation/application-state"

export function RuntimeRecordsPage() {
  const query = useRuntimeJobs()
  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-indigo-700">
            <ActivityIcon className="size-4" aria-hidden="true" />
            OPERATIONS
          </div>
          <h1 className="mt-2 text-2xl font-semibold">Agent 运行记录</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            展示 Job 固定的业务应用、Publication、Deployment 与 route 归因；历史记录不会按当前配置猜测回填。
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          <RefreshCwIcon
            className={query.isFetching ? "animate-spin" : ""}
            aria-hidden="true"
          />
          刷新
        </Button>
      </header>
      {query.isLoading ? <Skeleton className="h-72 w-full" /> : null}
      {query.isError ? (
        <ApplicationState
          error={query.error}
          retry={() => void query.refetch()}
        />
      ) : null}
      {query.data ? (
        <Card className="shadow-none">
          <CardContent className="p-0">
            <div className="divide-y">
              {query.data.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
              {!query.data.length ? (
                <p className="p-8 text-center text-sm text-muted-foreground">
                  当前时间窗口没有 Job。
                </p>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

function JobRow({ job }: { job: RuntimeJob }) {
  const attributed = Boolean(job.business_application_id)
  return (
    <article className="grid gap-3 p-4 text-sm lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] lg:items-center">
      <div className="min-w-0">
        <Link
          to={`/operations/jobs/${encodeURIComponent(job.id)}`}
          className="font-mono text-xs font-medium hover:underline"
        >
          {job.id}
        </Link>
        <p className="mt-1 text-xs text-muted-foreground">
          {job.source_channel} · {job.agent_code} · {formatDate(job.created_at)}
        </p>
      </div>
      <div className="min-w-0">
        <p className="font-medium">
          {attributed
            ? job.business_application_code
            : "历史兼容任务（无业务应用归因）"}
        </p>
        <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
          {attributed
            ? job.business_application_publication_id
            : "legacy_unattributed"}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge variant="secondary">{job.status}</Badge>
        <Badge variant="outline">
          {job.business_application_runtime_status}
        </Badge>
      </div>
    </article>
  )
}

export function RuntimeJobDetailPage() {
  const jobId = useParams().jobId ?? ""
  const query = useRuntimeJob(jobId)
  if (query.isLoading) return <PageSkeleton />
  if (query.isError || !query.data) {
    return (
      <PageFrame>
        <ApplicationState
          error={query.error}
          retry={() => void query.refetch()}
        />
      </PageFrame>
    )
  }
  const job = query.data.job
  return (
    <PageFrame>
      <PageBack />
      <h1 className="text-2xl font-semibold">Job 运行归因</h1>
      <p className="mt-1 font-mono text-xs text-muted-foreground">{job.id}</p>
      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <FactCard
          title="固定版本"
          rows={[
            ["业务应用", job.business_application_code || "legacy_unattributed"],
            ["Application ID", job.business_application_id || "未归因"],
            [
              "Publication",
              job.business_application_publication_id || "未归因",
            ],
            ["Deployment", job.business_application_deployment_id || "未归因"],
            ["Route", job.business_application_route_id || "未归因"],
            ["运行状态", job.business_application_runtime_status],
          ]}
        />
        <FactCard
          title="执行关联"
          rows={[
            ["状态", job.status],
            ["Agent", job.agent_code],
            ["Correlation ID", job.correlation_id || "无"],
            ["来源", job.source_channel],
            ["Connector", job.source_connector_id],
            ["创建时间", formatDate(job.created_at)],
          ]}
        />
      </div>
      <Card className="mt-4 shadow-none">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessagesSquareIcon className="size-4" aria-hidden="true" />
            会话
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Link
            className={buttonVariants({ variant: "outline" })}
            to={`/operations/conversations/${encodeURIComponent(job.session_id)}`}
          >
            查看会话与同会话 Job
          </Link>
        </CardContent>
      </Card>
    </PageFrame>
  )
}

export function ConversationDetailPage() {
  const sessionId = useParams().sessionId ?? ""
  const query = useConversation(sessionId)
  if (query.isLoading) return <PageSkeleton />
  if (query.isError || !query.data) {
    return (
      <PageFrame>
        <ApplicationState
          error={query.error}
          retry={() => void query.refetch()}
        />
      </PageFrame>
    )
  }
  const session = query.data.session
  return (
    <PageFrame>
      <PageBack />
      <h1 className="text-2xl font-semibold">会话归因</h1>
      <p className="mt-1 font-mono text-xs text-muted-foreground">{session.id}</p>
      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <FactCard
          title="会话策略"
          rows={[
            ["业务应用", session.business_application_code || "legacy"],
            ["Application ID", session.business_application_id || "未归因"],
            ["会话模式", session.conversation_mode],
            [
              "最近消息上限",
              String(session.recent_message_limit ?? "使用兼容默认值"),
            ],
            ["来源", session.source_channel],
            ["请求人", session.requester_id],
          ]}
        />
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>会话内 Job</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {query.data.jobs.map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </CardContent>
        </Card>
      </div>
    </PageFrame>
  )
}

function FactCard({
  title,
  rows,
}: {
  title: string
  rows: Array<[string, string]>
}) {
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="space-y-3 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="grid gap-1 sm:grid-cols-[10rem_1fr]">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="break-all font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  )
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-[1300px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      {children}
    </div>
  )
}

function PageBack() {
  return (
    <Link
      to="/operations/jobs"
      className={buttonVariants({ variant: "ghost", size: "sm" })}
    >
      <ArrowLeftIcon aria-hidden="true" />
      返回运行记录
    </Link>
  )
}

function PageSkeleton() {
  return (
    <PageFrame>
      <Skeleton className="h-8 w-72" />
      <Skeleton className="mt-5 h-72 w-full" />
    </PageFrame>
  )
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
