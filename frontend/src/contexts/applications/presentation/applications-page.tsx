import { Fragment, useState, type FormEvent } from "react"
import { ChevronDownIcon, LoaderCircleIcon, PlusIcon } from "lucide-react"
import { Link, useNavigate } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  ListEmpty,
  ListPage,
  ListPager,
  ListResults,
  ListSearch,
  ListStatus,
  ListStatusFilter,
  RefreshList,
} from "@/shared/presentation/list-page"
import { useListNavigation } from "@/shared/presentation/list-navigation"
import type { ApplicationSummary } from "@/contexts/applications/domain/business-application"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import {
  useApplications,
  useCreateApplication,
} from "@/contexts/applications/application/business-application-queries"
import { ApplicationState } from "@/contexts/applications/presentation/application-state"
import { RuntimeStatusBadge } from "@/contexts/applications/presentation/runtime-readiness"
import { ApiError } from "@/shared/api/api-client"

export function ApplicationsPage() {
  const list = useListNavigation()
  const search = list.params.get("q") ?? ""
  const status = list.params.get("status") ?? ""
  const query = useApplications(search, status, list.params.get("after") ?? "")
  const clear = () => list.filter({ q: "", status: "" })
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
        navigate(`/applications/${encodeURIComponent(application.code)}`, {
          state: list.detailState,
        })
      },
    })
  }

  return (
    <ListPage
      title="业务应用"
      actions={
        <>
          <RefreshList
            refresh={() => void query.refetch()}
            busy={query.isFetching}
          />
          <Button onClick={() => setShowCreate(true)}>
            <PlusIcon />
            新建应用
          </Button>
        </>
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <ListSearch
          label="搜索应用"
          placeholder="搜索应用名称或编码"
          value={search}
          onCommit={(q) => list.filter({ q })}
        />
        <ListStatusFilter
          value={status}
          archived
          onChange={(status) => list.filter({ status })}
        />
        {(search || status) && (
          <Button size="sm" variant="ghost" onClick={clear}>
            重置
          </Button>
        )}
      </div>
      <Sheet open={showCreate} onOpenChange={setShowCreate}>
        <SheetContent
          className="w-full overflow-y-auto sm:max-w-lg"
          aria-describedby={undefined}
        >
          <SheetHeader>
            <SheetTitle>新建业务应用</SheetTitle>
          </SheetHeader>
          <form onSubmit={submit} className="space-y-4 px-4 pb-5">
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
                  <LoaderCircleIcon
                    className="animate-spin"
                    aria-hidden="true"
                  />
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
        </SheetContent>
      </Sheet>
      {query.isLoading && (
        <Skeleton className="h-48" aria-label="正在加载业务应用" />
      )}
      {query.isError && (
        <ApplicationState
          error={query.error}
          retry={() => void query.refetch()}
        />
      )}
      {query.data && (
        <ListResults>
          {query.data.items.length ? (
            <Table aria-label="业务应用列表">
              <TableHeader>
                <TableRow>
                  <TableHead>应用名称</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>运行状态</TableHead>
                  <TableHead className="hidden md:table-cell">项目</TableHead>
                  <TableHead className="hidden sm:table-cell">
                    最新发布
                  </TableHead>
                  <TableHead className="hidden lg:table-cell">
                    激活环境
                  </TableHead>
                  <TableHead>
                    <span className="sr-only">更多信息</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.items.map((app) => (
                  <ApplicationRow
                    key={app.id}
                    app={app}
                    detailState={list.detailState}
                  />
                ))}
              </TableBody>
            </Table>
          ) : (
            <ListEmpty
              title={search || status ? "没有符合条件的应用" : "还没有业务应用"}
              clear={search || status ? clear : undefined}
            />
          )}
          <ListPager
            count={`本页 ${query.data.items.length} 个应用`}
            page={list.page}
            previous={list.previous}
            previousLabel={list.previousLabel}
            next={
              query.data.next_offset == null
                ? undefined
                : () => list.next(String(query.data.next_offset))
            }
          />
        </ListResults>
      )}
    </ListPage>
  )
}

function ApplicationRow({
  app,
  detailState,
}: {
  app: ApplicationSummary
  detailState: ReturnType<typeof useListNavigation>["detailState"]
}) {
  const [open, setOpen] = useState(false)
  return (
    <Fragment>
      <TableRow>
        <TableCell>
          <Link
            className="block max-w-[clamp(5.25rem,calc(100vw-16.5rem),9rem)] truncate font-medium hover:underline sm:max-w-72"
            title={app.name}
            to={`/applications/${encodeURIComponent(app.code)}`}
            state={detailState}
          >
            {app.name}
          </Link>
          <p
            className="mt-1 max-w-[clamp(5.25rem,calc(100vw-16.5rem),9rem)] truncate font-mono text-xs text-muted-foreground sm:max-w-72"
            title={app.code}
          >
            {app.code}
          </p>
        </TableCell>
        <TableCell>
          <ListStatus status={app.status} />
        </TableCell>
        <TableCell>
          <RuntimeStatusBadge state={app} />
        </TableCell>
        <TableCell className="hidden md:table-cell">
          {app.project_code}
        </TableCell>
        <TableCell className="hidden sm:table-cell">
          {app.latest_publication_revision
            ? `r${app.latest_publication_revision}`
            : "未发布"}
        </TableCell>
        <TableCell className="hidden lg:table-cell">
          {app.active_environments.join("、") || "未激活"}
        </TableCell>
        <TableCell className="text-right">
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={`${open ? "收起" : "展开"}${app.name}的信息`}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            <ChevronDownIcon className={open ? "rotate-180" : ""} />
          </Button>
        </TableCell>
      </TableRow>
      {open && (
        <TableRow>
          <TableCell colSpan={7} className="bg-muted/20 whitespace-normal">
            {app.description && <p className="mb-2">{app.description}</p>}
            <dl className="flex flex-wrap gap-x-8 gap-y-3 text-xs">
              <div className="md:hidden">
                <Definition label="项目" value={app.project_code} />
              </div>
              <div className="sm:hidden">
                <Definition
                  label="最新发布"
                  value={
                    app.latest_publication_revision
                      ? `r${app.latest_publication_revision}`
                      : "未发布"
                  }
                />
              </div>
              <div className="lg:hidden">
                <Definition
                  label="激活环境"
                  value={app.active_environments.join("、") || "未激活"}
                />
              </div>
              <Definition label="当前修订" value={`r${app.revision}`} />
              <Definition
                label="运行环境"
                value={app.runtime_environment || "未返回"}
              />
              <Definition
                label="工作区周期（当前修订）"
                value={
                  { DAY: "一天", WEEK: "一周", MONTH: "一个月" }[
                    app.task_workspace_retention_period
                  ]
                }
              />
              <Definition
                label="文档解析/OCR"
                value={
                  app.document_processing_profile_code === "NONE"
                    ? "关闭"
                    : app.document_processing_profile_code
                }
              />
            </dl>
          </TableCell>
        </TableRow>
      )}
    </Fragment>
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
    status === "enabled"
      ? "已启用"
      : status === "disabled"
        ? "已停用"
        : "已归档"
  return (
    <Badge variant={status === "enabled" ? "default" : "secondary"}>
      <span
        className="mr-1 size-1.5 rounded-full bg-current"
        aria-hidden="true"
      />
      {label}
    </Badge>
  )
}
