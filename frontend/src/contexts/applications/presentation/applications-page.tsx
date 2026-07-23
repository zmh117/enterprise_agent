import { useState, type FormEvent } from "react"
import {
  ArrowRightIcon,
  BoxesIcon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
} from "lucide-react"
import { Link, useNavigate } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import {
  useApplications,
  useCreateApplication,
} from "@/contexts/applications/application/business-application-queries"
import { ApplicationState } from "@/contexts/applications/presentation/application-state"
import { ApiError } from "@/shared/api/api-client"

export function ApplicationsPage() {
  const query = useApplications()
  const create = useCreateApplication()
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({
    code: "",
    name: "",
    description: "",
    project_code: "default",
    owner_user_id: "",
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(form, {
      onSuccess: (application) => {
        navigate(`/applications/${encodeURIComponent(application.code)}`)
      },
    })
  }

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-indigo-700">
            <BoxesIcon className="size-4" aria-hidden="true" />
            BUSINESS APPLICATIONS
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">业务应用</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            装配已发布 Agent、Workflow 和 Channel，经过校验后形成不可变发布快照。
            当前控制面尚未接管钉钉或 Webhook 运行时。
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
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
          <Button type="button" onClick={() => setShowCreate((value) => !value)}>
            <PlusIcon aria-hidden="true" />
            新建应用
          </Button>
        </div>
      </header>

      <RuntimeNotice />

      {showCreate ? (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>创建稳定应用定义</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="应用编码" htmlFor="application-code">
                  <Input
                    id="application-code"
                    required
                    pattern={"[a-z][a-z0-9_\\-]+"}
                    maxLength={120}
                    value={form.code}
                    onChange={(event) =>
                      setForm({ ...form, code: event.target.value })
                    }
                    placeholder="diagnostic-assistant"
                  />
                </Field>
                <Field label="应用名称" htmlFor="application-name">
                  <Input
                    id="application-name"
                    required
                    maxLength={200}
                    value={form.name}
                    onChange={(event) =>
                      setForm({ ...form, name: event.target.value })
                    }
                    placeholder="生产诊断助手"
                  />
                </Field>
                <Field label="项目编码" htmlFor="application-project">
                  <Input
                    id="application-project"
                    required
                    maxLength={120}
                    value={form.project_code}
                    onChange={(event) =>
                      setForm({ ...form, project_code: event.target.value })
                    }
                  />
                </Field>
                <Field label="负责人用户 ID（可选）" htmlFor="application-owner">
                  <Input
                    id="application-owner"
                    maxLength={200}
                    value={form.owner_user_id}
                    onChange={(event) =>
                      setForm({ ...form, owner_user_id: event.target.value })
                    }
                  />
                </Field>
              </div>
              <Field label="用途说明" htmlFor="application-description">
                <textarea
                  id="application-description"
                  className="min-h-24 w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  maxLength={4000}
                  value={form.description}
                  onChange={(event) =>
                    setForm({ ...form, description: event.target.value })
                  }
                />
              </Field>
              <MutationError error={create.error} />
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={create.isPending}>
                  {create.isPending ? (
                    <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
                  ) : null}
                  创建应用
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowCreate(false)}
                >
                  取消
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {query.isLoading ? <ApplicationListSkeleton /> : null}
      {query.isError ? (
        <ApplicationState
          error={query.error}
          retry={() => void query.refetch()}
        />
      ) : null}
      {query.data && query.data.length === 0 ? <EmptyApplications /> : null}
      {query.data && query.data.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {query.data.map((application) => (
            <Card key={application.id} className="shadow-none">
              <CardHeader className="border-b">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-base">{application.name}</CardTitle>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">
                      {application.code}
                    </p>
                  </div>
                  <StatusBadge status={application.status} />
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="min-h-12 text-sm leading-6 text-muted-foreground">
                  {application.description || "尚未填写用途说明。"}
                </p>
                <dl className="grid grid-cols-2 gap-3 text-xs">
                  <Definition label="项目" value={application.project_code} />
                  <Definition label="当前修订" value={`r${application.revision}`} />
                  <Definition
                    label="最新发布"
                    value={
                      application.latest_publication_revision
                        ? `r${application.latest_publication_revision}`
                        : "未发布"
                    }
                  />
                  <Definition
                    label="活动环境"
                    value={
                      application.active_environments.length
                        ? application.active_environments.join("、")
                        : "无"
                    }
                  />
                </dl>
                <Link
                  className={buttonVariants({
                    variant: "outline",
                    className: "w-full",
                  })}
                  to={`/applications/${encodeURIComponent(application.code)}`}
                >
                  进入应用工作区
                  <ArrowRightIcon aria-hidden="true" />
                </Link>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function RuntimeNotice() {
  return (
    <div
      className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100"
      role="status"
    >
      <strong>runtime_wired=false：</strong>
      发布和激活只更新控制面，不会启动 Agent Job，也不会切换现有钉钉或 Webhook
      路由。
    </div>
  )
}

function ApplicationListSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3" aria-label="正在加载业务应用">
      {[0, 1, 2].map((value) => (
        <Card key={value} className="shadow-none">
          <CardContent className="space-y-4 pt-6">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-9 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function EmptyApplications() {
  return (
    <Card className="shadow-none">
      <CardContent className="flex min-h-64 flex-col items-center justify-center text-center">
        <BoxesIcon className="size-8 text-muted-foreground" aria-hidden="true" />
        <h2 className="mt-4 font-semibold">还没有业务应用</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          创建稳定应用定义后，再选择已发布组件并执行校验。
        </p>
      </CardContent>
    </Card>
  )
}

export function MutationError({ error }: { error: unknown }) {
  if (!error) return null
  const apiError = error instanceof ApiError ? error : null
  return (
    <div
      role="alert"
      className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive"
    >
      <p className="font-medium">{apiError?.message ?? "操作失败，请重试。"}</p>
      {apiError?.status === 409 ? (
        <p className="mt-1 text-xs">
          当前修订已变化
          {apiError.currentRevision !== undefined
            ? `（服务器 r${apiError.currentRevision}）`
            : ""}
          ，请刷新后人工合并。
        </p>
      ) : null}
      {apiError?.fieldErrors.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
          {apiError.fieldErrors.map((item, index) => (
            <li key={`${item.field}-${index}`}>
              {item.field}: {item.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  )
}

function Definition({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-medium">{value}</dd>
    </div>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const label =
    status === "enabled" ? "已启用" : status === "disabled" ? "已停用" : "已归档"
  return (
    <Badge variant={status === "enabled" ? "default" : "secondary"}>
      <span className="mr-1 size-1.5 rounded-full bg-current" aria-hidden="true" />
      {label}
    </Badge>
  )
}
