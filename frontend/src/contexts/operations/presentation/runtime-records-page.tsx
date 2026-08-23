import {
  ActivityIcon,
  ArrowLeftIcon,
  MessagesSquareIcon,
  RefreshCwIcon,
} from "lucide-react"
import { Link, useParams } from "react-router-dom"
import { type ReactNode, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import {
  useConversation,
  useFileOperations,
  useRuntimeJob,
  useRuntimeJobs,
} from "@/contexts/operations/application/runtime-record-queries"
import {
  DOCUMENT_RUNTIME_FILE_FORMATS,
  TEXT_RUNTIME_FILE_FORMATS,
  type DeliveryAttempt,
  type DeliveryChunk,
  type DeliveryEvent,
  type ExecutionSummary,
  type FileOperations,
  type FileWorkspaceEvidence,
  type ModelCall,
  type ModelCallPage,
  type RuntimeJob,
} from "@/contexts/operations/domain/runtime-record"
import {
  listRuntimeJobModelCalls,
  type RuntimeJobFilters,
} from "@/contexts/operations/infrastructure/runtime-record-api"
import { ApplicationState } from "@/contexts/applications/presentation/application-state"

const RUNTIME_JOB_FILTER_FIELDS: Array<{
  key: keyof RuntimeJobFilters
  label: string
  type: "datetime-local" | "text"
  placeholder?: string
}> = [
  { key: "start", label: "开始时间", type: "datetime-local" },
  { key: "end", label: "结束时间", type: "datetime-local" },
  {
    key: "username",
    label: "用户名",
    type: "text",
    placeholder: "用户名或显示名称",
  },
  {
    key: "applicationName",
    label: "应用名",
    type: "text",
    placeholder: "应用名称或应用编码",
  },
]

export function RuntimeRecordsPage() {
  const [filters, setFilters] = useState<RuntimeJobFilters>(() =>
    defaultRuntimeJobFilters()
  )
  const [appliedFilters, setAppliedFilters] = useState(filters)
  const query = useRuntimeJobs(appliedFilters)
  const fileOperations = useFileOperations()
  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-indigo-700">
            <ActivityIcon className="size-4" aria-hidden="true" />
            运行中心
          </div>
          <h1 className="mt-2 text-2xl font-semibold">Agent 运行记录</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            展示用户、Agent、模型、工具、Token、耗时、估算成本和稳定失败位置；
            Agent 执行与结果投递保持独立。
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
      {fileOperations.data ? (
        <FileOperationsPanel value={fileOperations.data} />
      ) : null}
      <form
        className="grid gap-3 rounded-xl border p-4 sm:grid-cols-2 xl:grid-cols-4"
        aria-label="运行记录筛选"
        onSubmit={(event) => {
          event.preventDefault()
          setAppliedFilters(filters)
        }}
      >
        {RUNTIME_JOB_FILTER_FIELDS.map(({ key, label, type, placeholder }) => (
          <label key={key} className="space-y-1 text-xs text-muted-foreground">
            {label}
            <Input
              type={type}
              step={type === "datetime-local" ? 1 : undefined}
              value={filters[key] ?? ""}
              placeholder={placeholder}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  [key]: event.target.value,
                }))
              }
            />
          </label>
        ))}
        <div className="flex gap-2 sm:col-span-2 xl:col-span-4">
          <Button type="submit">应用筛选</Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              const defaults = defaultRuntimeJobFilters()
              setFilters(defaults)
              setAppliedFilters(defaults)
            }}
          >
            重置
          </Button>
        </div>
      </form>
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
                  当前时间窗口没有任务。
                </p>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

function FileOperationsPanel({ value }: { value: FileOperations }) {
  const queue = value.file_worker.attachment_queue
  const documentProcessing = value.document_processing
  const processingQueues = documentProcessing.queues
  const processingOperations = documentProcessing.operations
  const backlog = value.backlog
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          文件工作区运行状态
          <Badge
            variant={value.file_service.ready ? "secondary" : "destructive"}
          >
            File Service {value.file_service.ready ? "就绪" : "不可用"}
          </Badge>
          <Badge
            variant={value.file_worker.ready ? "secondary" : "destructive"}
          >
            File Worker {value.file_worker.ready ? "就绪" : "不可用"}
          </Badge>
          <Badge
            variant={documentProcessing.ready ? "secondary" : "destructive"}
          >
            文档解析/OCR {documentProcessing.ready ? "就绪" : "不可用"}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Metric
            label="附件队列"
            value={`ready ${queue.ready ?? "-"} · unacked ${queue.unacked ?? "-"} · consumer ${queue.consumers ?? "-"}`}
          />
          <Metric
            label="文档处理队列"
            value={`ready ${processingQueues.processing.ready ?? "-"} · unacked ${processingQueues.processing.unacked ?? "-"} · consumer ${processingQueues.processing.consumers ?? "-"}`}
          />
          <Metric
            label="文档处理重试 / DLQ"
            value={`retry ${processingQueues.retry.ready ?? "-"} · dead ${processingQueues.dead.ready ?? "-"}`}
          />
          <Metric
            label="文档处理依赖"
            value={`RabbitMQ ${formatDependencyState(documentProcessing.file_processing_worker.components.rabbitmq)} · File Service ${formatDependencyState(documentProcessing.file_processing_worker.components.file_service)} · Docling ${formatDependencyState(documentProcessing.file_processing_worker.components.docling)}`}
          />
          <Metric
            label="清理积压"
            value={`总计 ${backlog.cleanup} · staging ${backlog.staging} · 附件 ${backlog.attachment}`}
          />
          <Metric
            label="生命周期积压"
            value={`工作区 ${backlog.workspace} · 保留 ${backlog.retained} · 冲突 ${backlog.conflict} · 事件 ${backlog.domain_outbox}`}
          />
          <Metric
            label="最近清理结果"
            value={
              value.recent_cleanup
                ? `${value.recent_cleanup.status} · ${formatDate(value.recent_cleanup.updated_at)}`
                : "暂无记录"
            }
          />
        </div>
        <div className="grid gap-4 xl:grid-cols-3">
          <DocumentProcessingList title="处理分组">
            {processingOperations.groups.slice(0, 8).map((group) => (
              <li
                key={`${group.tenant_id}:${group.application_id}:${group.profile_code}:${group.status}`}
              >
                <p className="font-medium">
                  {group.application_code || group.application_id || "未归因应用"} ·{" "}
                  {group.profile_code} · {group.status}
                </p>
                <p className="text-xs text-muted-foreground">
                  tenant {group.tenant_id} · {group.count} 个 · attempt{" "}
                  {group.total_attempts} · 输入 {formatFileBytes(group.source_size_bytes)} ·
                  输出 {formatFileBytes(group.output_size_bytes)}
                </p>
              </li>
            ))}
            {!processingOperations.groups.length ? (
              <li className="text-muted-foreground">暂无处理运行</li>
            ) : null}
          </DocumentProcessingList>
          <DocumentProcessingList title="最近失败">
            {processingOperations.recent_failures.slice(0, 6).map((run) => (
              <li key={run.run_id}>
                <p className="font-mono text-xs">{run.run_id}</p>
                <p className="text-xs text-muted-foreground">
                  {run.application_code || "未归因应用"} · {run.error_code || "unknown"} ·
                  attempt {run.attempt}
                </p>
              </li>
            ))}
            {!processingOperations.recent_failures.length ? (
              <li className="text-muted-foreground">暂无失败</li>
            ) : null}
          </DocumentProcessingList>
          <DocumentProcessingList title="source → run → representation → Job">
            {processingOperations.traces.slice(0, 6).map((trace) => (
              <li key={trace.run_id}>
                <p className="font-mono text-xs">{trace.source_version_id}</p>
                <p className="font-mono text-xs text-muted-foreground">
                  {trace.run_id} → {trace.representations.length} representation
                  {trace.job_id ? " → " : ""}
                  {trace.job_id ? (
                    <Link
                      className="hover:underline"
                      to={`/operations/jobs/${encodeURIComponent(trace.job_id)}`}
                    >
                      {trace.job_id}
                    </Link>
                  ) : (
                    ""
                  )}
                </p>
              </li>
            ))}
            {!processingOperations.traces.length ? (
              <li className="text-muted-foreground">暂无血缘记录</li>
            ) : null}
          </DocumentProcessingList>
        </div>
      </CardContent>
    </Card>
  )
}

function DocumentProcessingList({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <section className="rounded-md border p-3">
      <h3 className="mb-2 font-medium">{title}</h3>
      <ul className="space-y-2">{children}</ul>
    </section>
  )
}

function formatFileBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`
}

function formatDependencyState(value: "ready" | "unavailable") {
  return value === "ready" ? "就绪" : "不可用"
}

function JobRow({ job }: { job: RuntimeJob }) {
  const attributed = Boolean(job.business_application_id)
  const summary = job.execution_summary
  return (
    <article className="grid gap-3 p-4 text-sm xl:grid-cols-[minmax(14rem,1.1fr)_minmax(11rem,.8fr)_minmax(18rem,1.4fr)_auto] xl:items-center">
      <div className="min-w-0">
        <Link
          to={`/operations/jobs/${encodeURIComponent(job.id)}`}
          className="font-mono text-xs font-medium hover:underline"
        >
          {job.id}
        </Link>
        <p className="mt-1 text-xs text-muted-foreground">
          用户 {runtimeUserLabel(job)} · {job.source_channel} ·{" "}
          {formatDate(job.created_at)}
        </p>
      </div>
      <div className="min-w-0">
        <p className="font-medium">
          {attributed
            ? runtimeApplicationLabel(job)
            : "历史兼容任务（无业务应用归因）"}
        </p>
        <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
          {attributed
            ? job.business_application_publication_id
            : "legacy_unattributed"}
        </p>
      </div>
      <div className="min-w-0 space-y-1 text-xs">
        <p className="font-medium">
          {summary.models.length ? summary.models.join("、") : "模型未知"}
        </p>
        <p className="text-muted-foreground">
          总耗时 {formatDuration(summary.total_duration_ms)} · API{" "}
          {formatDuration(summary.total_api_duration_ms)}
        </p>
        <p className="text-muted-foreground">
          输入 {formatCounter(summary.input_tokens)} · 输出{" "}
          {formatCounter(summary.output_tokens)} · 缓存创建{" "}
          {formatCounter(summary.cache_creation_input_tokens)} · 缓存读取{" "}
          {formatCounter(summary.cache_read_input_tokens)}
        </p>
        <p className="text-muted-foreground">
          估算成本 {formatCost(summary.estimated_cost_usd)} · 工具{" "}
          {job.tool_call_count} 次
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge variant="secondary">{jobStatusLabel(job.status)}</Badge>
        <Badge variant="outline">
          {accountingStatusLabel(summary.accounting_status)}
        </Badge>
        {summary.display_failure_stage ? (
          <Badge variant="destructive">
            {failureStageLabel(summary.display_failure_stage)}
          </Badge>
        ) : null}
        <Badge variant="outline">
          {runtimeStatusLabel(job.business_application_runtime_status)}
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
      <h1 className="text-2xl font-semibold">任务运行归因</h1>
      <p className="mt-1 font-mono text-xs text-muted-foreground">{job.id}</p>
      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        <FactCard
          title="固定版本"
          rows={[
            [
              "业务应用",
              job.business_application_code || "legacy_unattributed",
            ],
            ["业务应用 ID", job.business_application_id || "未归因"],
            ["发布版本", job.business_application_publication_id || "未归因"],
            ["部署 ID", job.business_application_deployment_id || "未归因"],
            ["路由 ID", job.business_application_route_id || "未归因"],
            [
              "运行状态",
              runtimeStatusLabel(job.business_application_runtime_status),
            ],
          ]}
        />
        <FactCard
          title="执行关联"
          rows={[
            ["状态", jobStatusLabel(job.status)],
            ["Agent", job.agent_code],
            ["关联 ID", job.correlation_id || "无"],
            ["来源", job.source_channel],
            ["连接器", sourceConnectorLabel(job)],
            ["创建时间", formatDate(job.created_at)],
          ]}
        />
        <FactCard
          title="固定执行策略"
          rows={[
            ["结构版本", `v${job.execution_policy.schema_version}`],
            ["请求限制", policyText(job.execution_policy.requested)],
            ["实际限制", policyText(job.execution_policy.effective)],
            [
              "Agent 发布版本",
              job.execution_policy.sources.agent_publication_id || "运行时默认",
            ],
            ["实际工具调用", String(job.tool_call_count)],
            [
              "策略耗尽",
              job.execution_policy_exhausted
                ? `是（${job.last_error_code}）`
                : "否",
            ],
          ]}
        />
      </div>
      <FileWorkspacePolicyPanel value={query.data.file_workspace} />
      <ExecutionAccountingPanel summary={query.data.execution_summary} />
      <ModelCallsPanel
        key={job.id}
        jobId={job.id}
        initialPage={query.data.model_calls}
      />
      <ExecutionEvidenceTimeline
        job={job}
        dispatch={query.data.dispatch}
        steps={query.data.steps}
        toolCalls={query.data.tool_calls}
        mcpOperationLinks={query.data.mcp_operation_links}
      />
      <DeliveryTimeline
        jobStatus={job.status}
        events={query.data.deliveries.events}
        attempts={query.data.deliveries.attempts}
        chunks={query.data.deliveries.chunks}
      />
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
            查看会话与同会话任务
          </Link>
        </CardContent>
      </Card>
    </PageFrame>
  )
}

function FileWorkspacePolicyPanel({
  value,
}: {
  value: FileWorkspaceEvidence
}) {
  const frozen = new Map(value.formats.map((item) => [item.format_code, item]))
  const matrix = [
    ["TXT", "读取、创建、编辑、提交、发送"],
    ["LOG", "只读并发送既有精确版本"],
    ["MARKDOWN", "读取、创建、编辑、提交、发送；不渲染正文"],
  ]
  const documentFormats = DOCUMENT_RUNTIME_FILE_FORMATS.filter((format) =>
    frozen.has(format)
  )
  const otherFormats = value.formats.filter(
    (item) =>
      !(TEXT_RUNTIME_FILE_FORMATS as readonly string[]).includes(
        item.format_code
      ) &&
      !(DOCUMENT_RUNTIME_FILE_FORMATS as readonly string[]).includes(
        item.format_code
      )
  )
  return (
    <Card className="mt-4 shadow-none">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          文件规则
          <Badge variant="outline">平台固定</Badge>
          <Badge variant={value.enabled ? "secondary" : "outline"}>
            {value.enabled ? "已冻结 Job Manifest" : "未创建文件清单"}
          </Badge>
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          来源 当前平台规则
          {value.manifest_schema_version
            ? ` · Manifest v${value.manifest_schema_version}`
            : ""}
          。这里只展示格式和操作摘要，不读取或渲染文件正文。
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <dl className="grid gap-3 text-sm lg:grid-cols-3">
          {matrix.map(([format, capability]) => {
            const item = frozen.get(format)
            return (
              <div key={format} className="rounded-lg border p-3">
                <dt className="font-medium">{format}</dt>
                <dd className="mt-1 text-xs text-muted-foreground">
                  {capability}
                </dd>
                <dd className="mt-2 text-xs">
                  输入 Manifest {item?.file_count ?? 0} 个文件
                  {item?.allowed_actions.length
                    ? ` · ${item.allowed_actions.join(" / ")}`
                    : ""}
                </dd>
              </div>
            )
          })}
        </dl>
        {documentFormats.length ? (
          <dl className="grid gap-3 text-sm lg:grid-cols-3">
            {documentFormats.map((format) => {
              const item = frozen.get(format)
              return (
                <div key={format} className="rounded-lg border p-3">
                  <dt className="font-medium">{format}</dt>
                  <dd className="mt-1 text-xs text-muted-foreground">
                    元数据、保留、发送原件；可读正文只走 Markdown 表示，原件不进沙盒
                  </dd>
                  <dd className="mt-2 text-xs">
                    输入 Manifest {item?.file_count ?? 0} 个文件
                    {item?.allowed_actions.length
                      ? ` · ${item.allowed_actions.join(" / ")}`
                      : ""}
                  </dd>
                </div>
              )
            })}
          </dl>
        ) : null}
        {otherFormats.length ? (
          <dl className="grid gap-3 text-sm lg:grid-cols-3">
            {otherFormats.map((item) => (
              <div key={item.format_code} className="rounded-lg border p-3">
                <dt className="font-medium">{item.format_code}</dt>
                <dd className="mt-1 text-xs text-muted-foreground">
                  清单已冻结该格式，页面仅展示计数和允许动作。
                </dd>
                <dd className="mt-2 text-xs">
                  输入 Manifest {item.file_count} 个文件
                  {item.allowed_actions.length
                    ? ` · ${item.allowed_actions.join(" / ")}`
                    : ""}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
        {value.output_commits.length ? (
          <div className="rounded-lg border p-3 text-sm">
            <p className="font-medium">本 Job 输出提交</p>
            <dl className="mt-2 space-y-1 text-xs">
              {value.output_commits.map((item) => (
                <div
                  key={`${item.format_code}:${item.status}`}
                  className="flex flex-wrap items-center gap-1"
                >
                  <dt>{item.format_code}</dt>
                  <dd>
                    · {item.commit_count} 个 · {item.status}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-xs text-muted-foreground">
              来源 File Commit Intent；仅展示格式、数量和状态，不回写输入
              Manifest。
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function ExecutionAccountingPanel({ summary }: { summary: ExecutionSummary }) {
  return (
    <Card className="mt-4 shadow-none">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          执行核算
          <Badge variant="outline">
            {accountingStatusLabel(summary.accounting_status)}
          </Badge>
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Agent 执行 {summary.execution_status} · Delivery{" "}
          {summary.delivery_status}
        </p>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <Metric
            label="总耗时"
            value={formatDuration(summary.total_duration_ms)}
          />
          <Metric
            label="模型 API 耗时"
            value={formatDuration(summary.total_api_duration_ms)}
          />
          <Metric
            label="输入 Token"
            value={formatCounter(summary.input_tokens)}
          />
          <Metric
            label="输出 Token"
            value={formatCounter(summary.output_tokens)}
          />
          <Metric
            label="缓存创建 Token"
            value={formatCounter(summary.cache_creation_input_tokens)}
          />
          <Metric
            label="缓存读取 Token"
            value={formatCounter(summary.cache_read_input_tokens)}
          />
          <Metric
            label="估算成本"
            value={formatCost(summary.estimated_cost_usd)}
          />
          <Metric
            label="模型轮次 / Runtime 调用"
            value={`${summary.observed_model_turn_count} 次 / ${summary.runtime_invocation_count} 次`}
          />
        </dl>
        <p className="mt-4 text-xs text-muted-foreground">
          <span>{summary.api_retry_count} 次 API 重试</span>
          {summary.display_failure_stage
            ? ` · 失败位置 ${failureStageLabel(summary.display_failure_stage)}`
            : " · 未定位到执行失败"}
          {summary.retry_exhausted ? " · Job 重试已耗尽" : ""}
        </p>
      </CardContent>
    </Card>
  )
}

function ModelCallsPanel({
  jobId,
  initialPage,
}: {
  jobId: string
  initialPage: ModelCallPage
}) {
  const [calls, setCalls] = useState<ModelCall[]>(initialPage.items)
  const [hasMore, setHasMore] = useState(initialPage.has_more)
  const [cursor, setCursor] = useState(initialPage.next_cursor)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [loadError, setLoadError] = useState("")

  async function loadMore() {
    if (!cursor || isLoadingMore) return
    setIsLoadingMore(true)
    setLoadError("")
    try {
      const page = await listRuntimeJobModelCalls(
        jobId,
        cursor,
        initialPage.limit
      )
      setCalls((current) => {
        const knownIds = new Set(current.map((call) => call.id))
        return [
          ...current,
          ...page.items.filter((call) => !knownIds.has(call.id)),
        ]
      })
      setHasMore(page.has_more)
      setCursor(page.next_cursor)
    } catch {
      setLoadError("加载更多模型请求失败，请重试。")
    } finally {
      setIsLoadingMore(false)
    }
  }

  return (
    <Card className="mt-4 shadow-none">
      <CardHeader>
        <CardTitle>模型请求</CardTitle>
        <p className="text-sm text-muted-foreground">
          只展示 SDK 安全标识和统计，不展示 Prompt、完整回复或原始 Provider
          载荷。
        </p>
      </CardHeader>
      <CardContent>
        {calls.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-b text-xs text-muted-foreground">
                <tr>
                  <th className="pb-2 font-medium">模型 / 标识</th>
                  <th className="pb-2 font-medium">状态</th>
                  <th className="pb-2 font-medium">耗时</th>
                  <th className="pb-2 font-medium">Token</th>
                  <th className="pb-2 font-medium">停止 / 错误</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {calls.map((call) => (
                  <tr key={call.id}>
                    <td className="py-3 pr-4">
                      <p className="font-medium">{call.model_id}</p>
                      {call.provider_request_id ? (
                        <p className="mt-1 font-mono text-xs text-muted-foreground">
                          Request {call.provider_request_id}
                        </p>
                      ) : null}
                      {call.provider_message_id ? (
                        <p className="font-mono text-xs text-muted-foreground">
                          Message {call.provider_message_id}
                        </p>
                      ) : null}
                      {!call.provider_request_id &&
                      !call.provider_message_id ? (
                        <p className="mt-1 text-xs text-muted-foreground">
                          标识不可用
                        </p>
                      ) : null}
                    </td>
                    <td className="py-3 pr-4">{call.status}</td>
                    <td className="py-3 pr-4">
                      {call.duration_source === "SDK_OBSERVED"
                        ? `SDK 观测 · ${formatDuration(call.duration_ms)}`
                        : "不可用（SDK 未提供请求起点）"}
                    </td>
                    <td className="py-3 pr-4 text-xs">
                      <p>
                        输入 {formatCounter(call.input_tokens)} · 输出{" "}
                        {formatCounter(call.output_tokens)}
                      </p>
                      <p className="mt-1 text-muted-foreground">
                        缓存创建{" "}
                        {formatCounter(call.cache_creation_input_tokens)} ·
                        缓存读取 {formatCounter(call.cache_read_input_tokens)}
                      </p>
                    </td>
                    <td className="py-3 text-xs">
                      {[
                        call.stop_reason ? `停止 ${call.stop_reason}` : "",
                        call.error_code ? `错误 ${call.error_code}` : "",
                        call.error_summary || "",
                      ]
                        .filter(Boolean)
                        .join(" · ") || "未知"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            没有可用的模型轮次统计。
          </p>
        )}
        {loadError ? (
          <p className="mt-3 text-xs text-destructive" role="alert">
            {loadError}
          </p>
        ) : null}
        {hasMore && cursor ? (
          <Button
            className="mt-3"
            type="button"
            variant="outline"
            size="sm"
            disabled={isLoadingMore}
            onClick={() => void loadMore()}
          >
            {isLoadingMore ? "加载中…" : "加载更多模型请求"}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-medium">{value}</dd>
    </div>
  )
}

function ExecutionEvidenceTimeline({
  job,
  dispatch,
  steps,
  toolCalls,
  mcpOperationLinks,
}: {
  job: RuntimeJob
  dispatch: Record<string, unknown> | null | undefined
  steps: Array<Record<string, unknown>>
  toolCalls: Array<Record<string, unknown>>
  mcpOperationLinks: Array<Record<string, string>>
}) {
  return (
    <div className="mt-4 grid gap-4 xl:grid-cols-3">
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>Agent 时间线</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="space-y-3" aria-label="Agent 执行时间线">
            <TimelineItem label="Job 创建" value={formatDate(job.created_at)} />
            {job.started_at ? (
              <TimelineItem
                label="开始执行"
                value={formatDate(job.started_at)}
              />
            ) : null}
            {steps.map((step, index) => (
              <TimelineItem
                key={String(step.id ?? index)}
                label={String(step.title ?? step.step_type ?? "执行步骤")}
                value={String(step.content ?? "")}
              />
            ))}
            {job.finished_at ? (
              <TimelineItem
                label="执行结束"
                value={formatDate(job.finished_at)}
              />
            ) : null}
          </ol>
        </CardContent>
      </Card>
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>Dispatch 时间线</CardTitle>
        </CardHeader>
        <CardContent>
          {dispatch ? (
            <dl className="grid gap-2 text-sm sm:grid-cols-[7rem_1fr]">
              <dt className="text-muted-foreground">状态</dt>
              <dd>{String(dispatch.status ?? "")}</dd>
              <dt className="text-muted-foreground">尝试</dt>
              <dd>
                {String(dispatch.attempt_count ?? 0)} /{" "}
                {String(dispatch.max_attempts ?? 0)}
              </dd>
              <dt className="text-muted-foreground">重放</dt>
              <dd>{String(dispatch.replay_count ?? 0)}</dd>
              <dt className="text-muted-foreground">下次处理</dt>
              <dd>{formatDate(String(dispatch.next_attempt_at ?? ""))}</dd>
              {dispatch.last_error_code || dispatch.last_error_summary ? (
                <>
                  <dt className="text-muted-foreground">安全错误</dt>
                  <dd className="break-all text-destructive">
                    {[dispatch.last_error_code, dispatch.last_error_summary]
                      .filter(Boolean)
                      .map(String)
                      .join(" · ")}
                  </dd>
                </>
              ) : null}
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">
              尚未找到 Job Dispatch Outbox 事件。
            </p>
          )}
        </CardContent>
      </Card>
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>Tool Call 时间线</CardTitle>
        </CardHeader>
        <CardContent>
          {toolCalls.length ? (
            <ol className="space-y-3" aria-label="工具调用时间线">
              {toolCalls.map((toolCall, index) => (
                <TimelineItem
                  key={String(toolCall.id ?? index)}
                  label={`${String(toolCall.tool_name ?? "tool")} · ${String(toolCall.status ?? "")}`}
                  value={formatToolResponseSummary(toolCall.response_summary)}
                />
              ))}
            </ol>
          ) : (
            <p className="text-sm text-muted-foreground">尚无工具调用。</p>
          )}
        </CardContent>
      </Card>
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>MCP 审计关联</CardTitle>
        </CardHeader>
        <CardContent>
          {mcpOperationLinks.length ? (
            <ol className="space-y-3" aria-label="MCP 审计关联列表">
              {mcpOperationLinks.map((link, index) => (
                <TimelineItem
                  key={`${link.agent_tool_call_id}:${link.mcp_call_id}:${index}`}
                  label={`${link.server_code || "MCP"} · ${link.mcp_call_id}`}
                  value={`Tool Call ${link.agent_tool_call_id}`}
                />
              ))}
            </ol>
          ) : (
            <p className="text-sm text-muted-foreground">尚无 MCP 审计关联。</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function TimelineItem({ label, value }: { label: string; value: string }) {
  return (
    <li className="border-l-2 pl-3">
      <p className="text-sm font-medium">{label}</p>
      <p className="mt-1 line-clamp-4 text-xs whitespace-pre-wrap text-muted-foreground">
        {value || "无摘要"}
      </p>
    </li>
  )
}

function DeliveryTimeline({
  jobStatus,
  events,
  attempts,
  chunks,
}: {
  jobStatus: string
  events: DeliveryEvent[]
  attempts: DeliveryAttempt[]
  chunks: DeliveryChunk[]
}) {
  const jobFinished = ["SUCCEEDED", "FAILED", "TIMEOUT"].includes(jobStatus)
  return (
    <Card className="mt-4 shadow-none">
      <CardHeader>
        <CardTitle>投递时间线</CardTitle>
        <p className="text-sm text-muted-foreground">
          Agent 执行与结果投递是两个独立状态；只有投递状态为 SUCCEEDED
          才表示已送达。
        </p>
      </CardHeader>
      <CardContent>
        {events.length ? (
          <ol className="space-y-4" aria-label="投递事件时间线">
            {events.map((event) => {
              const eventAttempts = attempts.filter(
                (attempt) => attempt.delivery_outbox_id === event.id
              )
              return (
                <li key={event.id} className="rounded-lg border p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-mono text-xs break-all">{event.id}</p>
                      <p className="mt-1 text-sm font-medium">
                        {deliveryOutcomeText(jobStatus, event.status)}
                      </p>
                    </div>
                    <Badge variant={deliveryBadgeVariant(event.status)}>
                      {deliveryStatusLabel(event.status)}
                    </Badge>
                  </div>
                  <dl className="mt-4 grid gap-2 text-xs sm:grid-cols-[minmax(7rem,9rem)_minmax(0,1fr)]">
                    <dt className="text-muted-foreground">路由</dt>
                    <dd className="break-all">
                      {event.route_type}
                      {event.connector_id ? ` · ${event.connector_id}` : ""}
                    </dd>
                    <dt className="text-muted-foreground">尝试次数</dt>
                    <dd>
                      {event.attempt_count} / {event.max_attempts}
                    </dd>
                    <dt className="text-muted-foreground">重放次数</dt>
                    <dd>
                      {event.replay_count} / {event.max_replay_count}
                    </dd>
                    {["PENDING", "RETRY_WAIT"].includes(event.status) ? (
                      <>
                        <dt className="text-muted-foreground">下次处理</dt>
                        <dd>{formatDate(event.next_attempt_at)}</dd>
                      </>
                    ) : null}
                    {event.last_error_code || event.last_error_summary ? (
                      <>
                        <dt className="text-muted-foreground">安全错误</dt>
                        <dd className="break-all text-destructive">
                          {[event.last_error_code, event.last_error_summary]
                            .filter(Boolean)
                            .join(" · ")}
                        </dd>
                      </>
                    ) : null}
                  </dl>
                  <AttemptTimeline attempts={eventAttempts} chunks={chunks} />
                </li>
              )
            })}
          </ol>
        ) : (
          <p className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
            {jobFinished
              ? "任务已结束，但缺少对应的投递事件；请检查事务与 Dispatcher。"
              : "Agent 尚未结束，暂未生成投递事件。"}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function AttemptTimeline({
  attempts,
  chunks,
}: {
  attempts: DeliveryAttempt[]
  chunks: DeliveryChunk[]
}) {
  if (!attempts.length) {
    return (
      <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">
        尚无投递尝试。
      </p>
    )
  }
  return (
    <ol className="mt-4 space-y-3 border-t pt-3" aria-label="投递尝试时间线">
      {attempts.map((attempt) => {
        const attemptChunks = chunks.filter(
          (chunk) => chunk.attempt_id === attempt.id
        )
        return (
          <li key={attempt.id} className="text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">
                {attempt.replay_no
                  ? `重放 ${attempt.replay_no} · 尝试 ${attempt.attempt_no}`
                  : `尝试 ${attempt.attempt_no}`}
              </span>
              <Badge variant={deliveryBadgeVariant(attempt.status)}>
                {deliveryAttemptStatusLabel(attempt.status)}
              </Badge>
              <span className="text-muted-foreground">
                {formatDate(attempt.created_at)}
              </span>
            </div>
            {attempt.error_code || attempt.error_message ? (
              <p className="mt-1 break-all text-destructive">
                {[attempt.error_code, attempt.error_message]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            ) : null}
            {attemptChunks.length ? (
              <ul className="mt-2 flex flex-wrap gap-2" aria-label="投递分片">
                {attemptChunks.map((chunk) => (
                  <li key={chunk.id}>
                    <Badge variant={deliveryBadgeVariant(chunk.status)}>
                      分片 {chunk.chunk_index}/{chunk.chunk_count} ·{" "}
                      {deliveryChunkStatusLabel(chunk.status)}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        )
      })}
    </ol>
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
      <header className="min-w-0">
        <h1 className="text-2xl font-semibold">会话归因</h1>
        <p className="mt-1 font-mono text-xs break-all text-muted-foreground">
          {session.id}
        </p>
      </header>
      <div className="mt-5 grid gap-4 2xl:grid-cols-[minmax(18rem,0.72fr)_minmax(0,1.28fr)] 2xl:items-start">
        <FactCard
          title="会话策略"
          rows={[
            ["业务应用", session.business_application_code || "legacy"],
            ["业务应用 ID", session.business_application_id || "未归因"],
            ["会话模式", conversationModeLabel(session.conversation_mode)],
            [
              "最近消息上限",
              String(session.recent_message_limit ?? "使用兼容默认值"),
            ],
            ["来源", session.source_channel],
            ["请求人", session.requester_id],
          ]}
        />
        <Card className="min-w-0 overflow-hidden shadow-none">
          <CardHeader className="flex flex-row items-center justify-between gap-3">
            <CardTitle>会话内任务</CardTitle>
            <Badge variant="secondary">{query.data.jobs.length} 个</Badge>
          </CardHeader>
          <CardContent className="p-0">
            {query.data.jobs.length ? (
              <ul className="divide-y" aria-label="会话内任务列表">
                {query.data.jobs.map((job) => (
                  <li key={job.id}>
                    <ConversationJobRow job={job} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-5 py-10 text-center text-sm text-muted-foreground">
                当前会话还没有任务。
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </PageFrame>
  )
}

function ConversationJobRow({ job }: { job: RuntimeJob }) {
  const attributed = Boolean(job.business_application_id)
  return (
    <article className="min-w-0 px-5 py-4 text-sm">
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <Link
            to={`/operations/jobs/${encodeURIComponent(job.id)}`}
            title={job.id}
            className="block truncate font-mono text-xs font-medium hover:underline"
          >
            {job.id}
          </Link>
          <p className="mt-1 text-xs text-muted-foreground">
            {job.source_channel} · {job.agent_code} ·{" "}
            {formatDate(job.created_at)}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
          <Badge variant="secondary">{jobStatusLabel(job.status)}</Badge>
          <Badge variant="outline">
            {runtimeStatusLabel(job.business_application_runtime_status)}
          </Badge>
        </div>
      </div>
      <dl className="mt-3 grid min-w-0 gap-2 border-t pt-3 text-xs sm:grid-cols-[minmax(7rem,9rem)_minmax(0,1fr)]">
        <dt className="text-muted-foreground">业务应用</dt>
        <dd className="min-w-0 font-medium break-all">
          {attributed
            ? job.business_application_code
            : "历史兼容任务（无业务应用归因）"}
        </dd>
        <dt className="text-muted-foreground">发布版本</dt>
        <dd className="min-w-0 font-mono break-all text-muted-foreground">
          {attributed
            ? job.business_application_publication_id
            : "legacy_unattributed"}
        </dd>
      </dl>
    </article>
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
            <div
              key={label}
              className="grid min-w-0 gap-1 sm:grid-cols-[minmax(7rem,9rem)_minmax(0,1fr)]"
            >
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="min-w-0 font-medium break-all">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  )
}

const jobStatusLabels: Record<string, string> = {
  WAITING_INPUT: "等待输入",
  PENDING: "等待执行",
  RUNNING: "执行中",
  RETRY_WAIT: "等待重试",
  SUCCEEDED: "已成功",
  FAILED: "已失败",
  TIMEOUT: "已超时",
}

const runtimeStatusLabels: Record<string, string> = {
  not_wired: "未接管",
  partially_wired: "部分接管",
  wired: "已接管",
  blocked: "已阻塞",
  legacy_unattributed: "旧版记录（未归因）",
}

const conversationModeLabels: Record<string, string> = {
  channel: "按渠道会话",
  actor: "按当前主体",
  application: "按业务应用",
  legacy: "旧版兼容模式",
}

const deliveryStatusLabels: Record<string, string> = {
  PENDING: "投递待处理",
  RUNNING: "投递中",
  RETRY_WAIT: "投递等待重试",
  SUCCEEDED: "已送达",
  FAILED: "投递失败",
  DEAD: "投递已耗尽",
  SKIPPED: "无需投递",
}

const deliveryAttemptStatusLabels: Record<string, string> = {
  RUNNING: "处理中",
  SUCCEEDED: "尝试成功",
  FAILED: "尝试失败",
  SKIPPED: "已跳过",
}

const deliveryChunkStatusLabels: Record<string, string> = {
  RUNNING: "处理中",
  SUCCEEDED: "已送达",
  FAILED: "发送失败",
  SKIPPED: "已跳过",
}

const failureStageLabels: Record<string, string> = {
  RUNTIME_START: "Runtime 启动",
  RUNTIME_PROTOCOL: "Runtime 协议",
  MCP_CONNECTION: "MCP 连接",
  MODEL_API: "模型 API",
  TOOL_PERMISSION: "工具权限",
  TOOL_EXECUTION: "工具执行",
  DELIVERY: "结果投递",
  UNKNOWN: "未知位置",
}

function jobStatusLabel(status: string): string {
  return jobStatusLabels[status] ?? status
}

function runtimeStatusLabel(status: string): string {
  return runtimeStatusLabels[status] ?? status
}

function sourceConnectorLabel(job: RuntimeJob): string {
  if (!job.source_connector_id) return "未记录"
  const identity = job.source_connector_name
    ? `${job.source_connector_name}（${job.source_connector_id}）`
    : job.source_connector_id
  return job.source_connector_availability === "UNAVAILABLE_HISTORICAL"
    ? `${identity} · 不可用历史来源`
    : identity
}

function runtimeUserLabel(job: RuntimeJob): string {
  const displayName = job.user_display_name.trim()
  const username = job.user_username.trim()
  if (displayName && username) return `${displayName}（@${username}）`
  if (displayName) return displayName
  if (username) return `@${username}`
  if (job.internal_user_id) return `历史用户（${job.internal_user_id}）`
  return "用户未知"
}

function runtimeApplicationLabel(job: RuntimeJob): string {
  const name = job.business_application_name.trim()
  const code = job.business_application_code.trim()
  if (name && code && name !== code) return `${name}（${code}）`
  return name || code || "历史应用"
}

function defaultRuntimeJobFilters(now = new Date()): RuntimeJobFilters {
  const start = new Date(now.getTime() - 24 * 60 * 60 * 1000)
  return {
    start: localDateTimeInput(start),
    end: localDateTimeInput(now),
    username: "",
    applicationName: "",
  }
}

function localDateTimeInput(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 19)
}

function conversationModeLabel(mode: string): string {
  return conversationModeLabels[mode] ?? mode
}

function deliveryStatusLabel(status: string): string {
  return deliveryStatusLabels[status] ?? status
}

function deliveryAttemptStatusLabel(status: string): string {
  return deliveryAttemptStatusLabels[status] ?? status
}

function deliveryChunkStatusLabel(status: string): string {
  return deliveryChunkStatusLabels[status] ?? status
}

function accountingStatusLabel(status: string): string {
  if (status === "COMPLETE") return "统计完整"
  if (status === "PARTIAL") return "统计部分可用"
  return "统计不可用"
}

function failureStageLabel(stage: string): string {
  return failureStageLabels[stage] ?? stage
}

function deliveryOutcomeText(
  jobStatus: string,
  deliveryStatus: string
): string {
  const job =
    jobStatus === "SUCCEEDED" ? "Agent 已完成" : jobStatusLabel(jobStatus)
  return `${job} · ${deliveryStatusLabel(deliveryStatus)}`
}

function deliveryBadgeVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "SUCCEEDED") return "default"
  if (status === "FAILED" || status === "DEAD") return "destructive"
  if (status === "RUNNING" || status === "RETRY_WAIT") return "secondary"
  return "outline"
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

function formatDuration(value: number | null): string {
  return value === null ? "未知" : `${(value / 1000).toFixed(2)} 秒`
}

function formatCounter(value: number | null): string {
  return value === null ? "未知" : value.toLocaleString()
}

function formatToolResponseSummary(value: unknown): string {
  if (value === null || value === undefined || value === "") return ""

  const summary = structuredSummary(value)
  if (!summary) {
    return typeof value === "string" ? value : "已记录结构化安全摘要"
  }

  const parts: string[] = []
  const total = safeSummaryCount(summary.total)
  if (total !== null) parts.push(`返回 ${total.toLocaleString()} 项`)

  if (typeof summary.truncated === "boolean") {
    parts.push(summary.truncated ? "已截断" : "未截断")
  }
  if (summary.untrusted_data === true) {
    parts.push("含外部不受信任数据")
  }
  if (parts.length) return parts.join(" · ")

  if (summary.is_error === true) return "工具返回错误"
  if (summary.available === false) return "无可用安全摘要"
  return "已记录结构化安全摘要"
}

function structuredSummary(value: unknown): Record<string, unknown> | null {
  if (typeof value === "string") {
    try {
      const parsed: unknown = JSON.parse(value)
      return isSummaryRecord(parsed) ? parsed : null
    } catch {
      return null
    }
  }
  return isSummaryRecord(value) ? value : null
}

function isSummaryRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function safeSummaryCount(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : null
}

function formatCost(value: string | null): string {
  if (value === null) return "未知"
  const amount = Number(value)
  return Number.isFinite(amount) ? `$${amount.toFixed(6)}` : "未知"
}

function policyText(value: {
  max_turns: number
  timeout_seconds: number
  max_tool_calls: number
}) {
  return `${value.max_turns} 轮 · ${value.timeout_seconds} 秒 · ${value.max_tool_calls} 次工具调用`
}
