import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  BugIcon,
  RefreshCwIcon,
  SendIcon,
  SquareIcon,
} from "lucide-react"
import { useNavigate, useParams } from "react-router-dom"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import {
  useAdminRuntimeJob,
  useAdminRuntimeJobs,
} from "@/contexts/operations/application/runtime-record-queries"
import {
  cancelAdminJob,
  createDebugJob,
  listDebugApplications,
} from "@/contexts/operations/infrastructure/runtime-record-api"
import {
  JobRow,
  RuntimeErrorState,
  RuntimeJobEvidenceView,
  RuntimePageFrame,
} from "@/contexts/operations/presentation/runtime-records-page"
import {
  ManagementError,
  ManagementLoading,
  ManagementPage,
  MutationNotice,
} from "@/shared/presentation/management-states"
import { SectionHeading } from "@/shared/presentation/section-heading"

const adminJobsKey = ["admin", "operations", "jobs"] as const

export function AdminRuntimeRecordsPage() {
  const query = useAdminRuntimeJobs()
  return (
    <ManagementPage>
      <SectionHeading
        eyebrow="Operations Governance"
        title="运行历史"
        description="平台管理员可查看全局安全摘要；其他治理角色仅能查看本人范围。详情保留冻结的 Agent、Application Publication、MCP Resource Revision 与投递证据。"
        action={
          <Button variant="outline" onClick={() => void query.refetch()} disabled={query.isFetching}>
            <RefreshCwIcon className={query.isFetching ? "animate-spin" : ""} />刷新
          </Button>
        }
      />
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error} retry={() => void query.refetch()} />
      {query.data ? (
        <Card className="shadow-none">
          <CardContent className="divide-y p-0">
            {query.data.map((job) => (
              <JobRow key={job.id} job={job} detailBase="/operations/history" />
            ))}
            {!query.data.length ? (
              <p className="p-8 text-center text-sm text-muted-foreground">当前范围暂无任务。</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </ManagementPage>
  )
}

export function AdminRuntimeJobDetailPage() {
  const jobId = useParams().jobId ?? ""
  const query = useAdminRuntimeJob(jobId)
  const client = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const mutation = useMutation({
    mutationFn: cancelAdminJob,
    onSuccess: async () => {
      setConfirming(false)
      await Promise.all([
        client.invalidateQueries({ queryKey: adminJobsKey }),
        client.invalidateQueries({ queryKey: [...adminJobsKey, jobId] }),
      ])
    },
  })
  if (query.isLoading) {
    return <RuntimePageFrame><Skeleton className="h-8 w-72" /><Skeleton className="h-80 w-full" /></RuntimePageFrame>
  }
  if (query.isError || !query.data) {
    return <RuntimePageFrame><RuntimeErrorState error={query.error} retry={() => void query.refetch()} /></RuntimePageFrame>
  }
  const cancellableStatus = isCancellable(query.data.job.status)
    ? query.data.job.status
    : null
  return (
    <>
      <RuntimeJobEvidenceView
        evidence={query.data}
        backHref="/operations/history"
        backLabel="返回治理运行历史"
        action={cancellableStatus ? (
          <Button type="button" variant="outline" onClick={() => setConfirming(true)}>
            <SquareIcon />取消任务
          </Button>
        ) : undefined}
      />
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认取消此 Job？</AlertDialogTitle>
            <AlertDialogDescription>
              只会按当前状态执行一次受控状态迁移，不会删除 Job、历史证据或已冻结的 Publication。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <MutationNotice error={mutation.error} />
          <AlertDialogFooter>
            <AlertDialogCancel>返回</AlertDialogCancel>
            <AlertDialogAction
              disabled={mutation.isPending}
              onClick={(event) => {
                event.preventDefault()
                if (cancellableStatus) {
                  mutation.mutate({ id: query.data.job.id, status: cancellableStatus })
                }
              }}
            >
              {mutation.isPending ? "正在取消…" : "确认取消"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

export function DebugJobPage() {
  const navigate = useNavigate()
  const applications = useQuery({
    queryKey: ["admin", "operations", "debug-applications"],
    queryFn: listDebugApplications,
  })
  const [selection, setSelection] = useState("")
  const [message, setMessage] = useState("")
  const mutation = useMutation({
    mutationFn: createDebugJob,
    onSuccess: (job) => navigate(`/operations/history/${encodeURIComponent(job.id)}`),
  })
  const selected = applications.data?.find(
    (item) => `${item.code}\u0000${item.environment}` === selection
  )
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!selected || !message.trim()) return
    mutation.mutate({
      applicationCode: selected.code,
      environment: selected.environment,
      message: message.trim(),
    })
  }
  return (
    <ManagementPage>
      <SectionHeading
        eyebrow="Governed Debug"
        title="发起调试"
        description="只能选择当前账户有权使用且已激活的 Application。服务端固定主体、Agent/Application Publication、MCP Tool 与 Resource Generation，调试结果不会投递到外部渠道。"
      />
      {applications.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={applications.error} retry={() => void applications.refetch()} />
      <MutationNotice error={mutation.error} />
      {applications.data ? (
        <Card className="max-w-3xl shadow-none">
          <CardContent className="p-5">
            <form className="space-y-5" onSubmit={submit}>
              <div className="space-y-2">
                <Label htmlFor="debug-application">Application 与环境</Label>
                <select
                  id="debug-application"
                  className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                  value={selection}
                  onChange={(event) => setSelection(event.target.value)}
                  required
                >
                  <option value="">请选择当前可用 Application</option>
                  {applications.data.map((item) => (
                    <option key={`${item.id}:${item.environment}`} value={`${item.code}\u0000${item.environment}`}>
                      {item.name}（{item.code} · {item.environment === "production" ? "生产" : "测试"}）
                    </option>
                  ))}
                </select>
                {!applications.data.length ? (
                  <p className="text-sm text-muted-foreground">
                    当前账户没有可调试的已激活 Application，请先完成 Application 授权与环境激活。
                  </p>
                ) : null}
              </div>
              <div className="space-y-2">
                <Label htmlFor="debug-message">调试消息</Label>
                <Textarea
                  id="debug-message"
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  maxLength={12_000}
                  rows={8}
                  placeholder="描述要验证的问题，不要粘贴密码、Token 或连接串。"
                  required
                />
                <p className="text-xs text-muted-foreground">{message.length}/12000</p>
              </div>
              <Button type="submit" disabled={!selected || !message.trim() || mutation.isPending}>
                {mutation.isPending ? <BugIcon className="animate-pulse" /> : <SendIcon />}
                {mutation.isPending ? "正在创建…" : "创建调试 Job"}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : null}
    </ManagementPage>
  )
}

function isCancellable(
  status: string
): status is "WAITING_INPUT" | "PENDING" | "RUNNING" | "RETRY_WAIT" {
  return ["WAITING_INPUT", "PENDING", "RUNNING", "RETRY_WAIT"].includes(status)
}
