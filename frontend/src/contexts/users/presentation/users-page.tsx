import { useState, type FormEvent } from "react"
import { LoaderCircleIcon, PlusIcon } from "lucide-react"
import { Link, useNavigate } from "react-router-dom"

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
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
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
  useCreateUser,
  useUsers,
} from "@/contexts/users/application/user-queries"
import { useDingTalkIdentityCandidate } from "@/contexts/dingtalk-identity-discovery/application/dingtalk-identity-candidate-queries"
import { Field, RequestError } from "@/contexts/users/presentation/user-ui"
import { formatDate } from "@/contexts/users/presentation/format-date"

const PAGE_SIZE = 20

export function UsersPage() {
  const navigate = useNavigate()
  const list = useListNavigation()
  const searchParams = list.params
  const candidateId = searchParams.get("candidate")?.trim() ?? ""
  const candidate = useDingTalkIdentityCandidate(candidateId)
  const candidateSelectable =
    !candidateId || candidate.data?.identity_state === "waiting_bind"
  const search = searchParams.get("q") ?? ""
  const status = candidateId ? "" : (searchParams.get("status") ?? "")
  const clear = () => list.filter({ q: "", status: "" })
  const page = list.page
  const [creating, setCreating] = useState(false)
  const query = useUsers({
    search,
    status,
    page,
    pageSize: PAGE_SIZE,
    includeDisabled: !candidateId,
  })

  return (
    <ListPage
      title="人员管理"
      actions={
        <>
          <RefreshList
            refresh={() => void query.refetch()}
            busy={query.isFetching}
          />
          <Button
            onClick={() => setCreating(true)}
            disabled={Boolean(candidateId) && !candidateSelectable}
          >
            <PlusIcon />
            新建用户
          </Button>
        </>
      }
    >
      {candidateId ? (
        <Card className="border-indigo-200 bg-indigo-50/60 shadow-none">
          <CardContent>
            {candidate.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
                正在加载待绑定钉钉用户…
              </div>
            ) : null}
            {candidate.isError ? (
              <RequestError error={candidate.error} />
            ) : null}
            {candidate.data ? (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="font-medium">请选择要绑定的人员</div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    钉钉用户：
                    {candidate.data.display_name || "未提供用户名"} · 用户 ID{" "}
                    <span className="font-mono">
                      {candidate.data.external_subject_id}
                    </span>
                  </p>
                  {!candidateSelectable ? (
                    <p className="mt-2 text-sm text-amber-700">
                      该身份已有历史归属，只能前往原人员详情恢复。
                    </p>
                  ) : null}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => navigate("/users/dingtalk-discovery")}
                >
                  取消绑定
                </Button>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <ListSearch
          label="搜索用户"
          placeholder="用户名、显示名称、邮箱或外部身份"
          value={search}
          onCommit={(q) => list.filter({ q })}
        />
        {!candidateId && (
          <ListStatusFilter
            value={status}
            onChange={(status) => list.filter({ status })}
          />
        )}
        {(search || status) && (
          <Button size="sm" variant="ghost" onClick={clear}>
            重置
          </Button>
        )}
      </div>
      {query.isLoading ? (
        <div
          className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground"
          aria-label="正在加载用户"
        >
          <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
          正在加载用户…
        </div>
      ) : null}
      {query.isError ? <RequestError error={query.error} /> : null}
      {query.data ? (
        <ListResults>
          {query.data.users.length ? (
            <Table aria-label="人员列表">
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">用户</TableHead>
                  <TableHead className="hidden sm:table-cell">
                    账号类型
                  </TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="hidden md:table-cell">
                    更新时间
                  </TableHead>
                  {candidateId && (
                    <TableHead className="pr-4 text-right">操作</TableHead>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell className="pl-4">
                      {candidateId ? (
                        <span className="font-medium">{user.display_name}</span>
                      ) : (
                        <Link
                          className="font-medium hover:underline"
                          to={`/users/${encodeURIComponent(user.id)}`}
                          state={list.detailState}
                        >
                          {user.display_name}
                        </Link>
                      )}
                      <div className="mt-1 max-w-48 truncate text-xs text-muted-foreground sm:max-w-sm">
                        {user.username}
                        {user.email ? ` · ${user.email}` : ""}
                      </div>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <span>
                        {user.account_type === "human"
                          ? "人员账号"
                          : "服务账号"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <ListStatus status={user.status} />
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground md:table-cell">
                      {formatDate(user.updated_at)}
                    </TableCell>
                    {candidateId && (
                      <TableCell className="pr-4 text-right">
                        {user.account_type !== "human" ||
                        user.status !== "enabled" ||
                        !candidateSelectable ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled
                          >
                            不可绑定
                          </Button>
                        ) : (
                          <Link
                            className={buttonVariants({
                              variant: "outline",
                              size: "sm",
                            })}
                            state={list.detailState}
                            to={`/users/${encodeURIComponent(user.id)}?candidate=${encodeURIComponent(candidateId)}`}
                          >
                            选择并绑定
                          </Link>
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <ListEmpty
              title={
                search || status
                  ? "没有符合条件的用户"
                  : candidateId
                    ? "没有可供选择的用户"
                    : "还没有内部用户"
              }
              clear={search || status ? clear : undefined}
            />
          )}
          <ListPager
            count={`共 ${query.data.pagination.total} 个用户`}
            page={page}
            pages={query.data.pagination.total_pages}
            previous={() => list.numberedPage(page - 1)}
            next={
              page < query.data.pagination.total_pages
                ? () => list.numberedPage(page + 1)
                : undefined
            }
          />
        </ListResults>
      ) : null}

      {creating ? (
        <CreateUserSheet
          open
          onOpenChange={setCreating}
          candidateId={candidateSelectable ? candidateId : ""}
          candidateDisplayName={candidate.data?.display_name ?? ""}
          detailState={list.detailState}
        />
      ) : null}
    </ListPage>
  )
}

function CreateUserSheet({
  open,
  onOpenChange,
  candidateId,
  candidateDisplayName,
  detailState,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  candidateId: string
  candidateDisplayName: string
  detailState: ReturnType<typeof useListNavigation>["detailState"]
}) {
  const navigate = useNavigate()
  const mutation = useCreateUser()
  const [form, setForm] = useState({
    username: "",
    display_name: candidateDisplayName,
    email: "",
    password: "",
  })

  const reset = () =>
    setForm({
      username: "",
      display_name: candidateDisplayName,
      email: "",
      password: "",
    })

  const changeOpen = (nextOpen: boolean) => {
    if (!nextOpen) {
      reset()
      mutation.reset()
    }
    onOpenChange(nextOpen)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    mutation.mutate(form, {
      onSuccess: (user) => {
        if (candidateId) {
          navigate(
            `/users/${encodeURIComponent(user.id)}?candidate=${encodeURIComponent(candidateId)}`,
            { state: detailState }
          )
        }
        changeOpen(false)
      },
      onSettled: () => setForm((value) => ({ ...value, password: "" })),
    })
  }

  return (
    <Sheet open={open} onOpenChange={changeOpen}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>新建内部用户</SheetTitle>
          <SheetDescription>
            {candidateId
              ? "创建人员后继续进入详情，确认并绑定当前钉钉身份。"
              : "创建人员账号后，再进入详情绑定钉钉或 ONES 身份。"}
          </SheetDescription>
        </SheetHeader>
        <form className="space-y-4 px-4" onSubmit={submit}>
          <Field label="用户名" htmlFor="new-user-username">
            <Input
              id="new-user-username"
              required
              maxLength={120}
              autoComplete="off"
              value={form.username}
              onChange={(event) =>
                setForm({ ...form, username: event.target.value })
              }
            />
          </Field>
          <Field label="显示名称" htmlFor="new-user-display-name">
            <Input
              id="new-user-display-name"
              required
              maxLength={200}
              value={form.display_name}
              onChange={(event) =>
                setForm({ ...form, display_name: event.target.value })
              }
            />
          </Field>
          <Field label="邮箱（可选）" htmlFor="new-user-email">
            <Input
              id="new-user-email"
              type="email"
              maxLength={320}
              value={form.email}
              onChange={(event) =>
                setForm({ ...form, email: event.target.value })
              }
            />
          </Field>
          <Field
            label="初始密码（可选）"
            htmlFor="new-user-password"
            hint="设置时至少 12 位；提交后不会再次显示。"
          >
            <Input
              id="new-user-password"
              type="password"
              minLength={12}
              maxLength={512}
              autoComplete="new-password"
              value={form.password}
              onChange={(event) =>
                setForm({ ...form, password: event.target.value })
              }
            />
          </Field>
          <RequestError error={mutation.error} />
          <SheetFooter className="px-0">
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : null}
              创建用户
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => changeOpen(false)}
            >
              取消
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  )
}
