import { useState, type FormEvent } from "react"
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  UsersIcon,
} from "lucide-react"
import { Link } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
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
import {
  Field,
  RequestError,
  UserStatusBadge,
} from "@/contexts/users/presentation/user-ui"
import { formatDate } from "@/contexts/users/presentation/format-date"

const PAGE_SIZE = 20

export function UsersPage() {
  const [draftSearch, setDraftSearch] = useState("")
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const query = useUsers({
    search,
    page,
    pageSize: PAGE_SIZE,
    includeDisabled: true,
  })

  const submitSearch = (event: FormEvent) => {
    event.preventDefault()
    setPage(1)
    setSearch(draftSearch.trim())
  }

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-indigo-700">
            <UsersIcon className="size-4" aria-hidden="true" />
            USERS & EXTERNAL IDENTITIES
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">
            用户与外部身份
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            维护内部人员，并在用户详情中绑定钉钉和 ONES 身份。身份关联用于确认主体，
            不会自动授予角色或业务数据权限。
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
          <Button type="button" onClick={() => setCreating(true)}>
            <PlusIcon aria-hidden="true" />
            新建用户
          </Button>
        </div>
      </header>

      <Card className="shadow-none">
        <CardContent>
          <form
            onSubmit={submitSearch}
            className="flex flex-col gap-2 sm:flex-row"
            role="search"
          >
            <div className="relative flex-1">
              <SearchIcon
                className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                aria-label="搜索用户"
                className="pl-8"
                value={draftSearch}
                onChange={(event) => setDraftSearch(event.target.value)}
                placeholder="用户名、显示名称、邮箱或外部身份"
              />
            </div>
            <Button type="submit" variant="outline">
              搜索
            </Button>
          </form>
        </CardContent>
      </Card>

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
        <Card className="shadow-none">
          <CardContent className="px-0">
            {query.data.users.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">用户</TableHead>
                    <TableHead>账号类型</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>更新时间</TableHead>
                    <TableHead className="pr-4 text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {query.data.users.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell className="pl-4">
                        <div className="font-medium">{user.display_name}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {user.username}
                          {user.email ? ` · ${user.email}` : ""}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">
                          {user.account_type === "human"
                            ? "人员账号"
                            : "服务账号"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <UserStatusBadge status={user.status} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(user.updated_at)}
                      </TableCell>
                      <TableCell className="pr-4 text-right">
                        <Link
                          className={buttonVariants({
                            variant: "outline",
                            size: "sm",
                          })}
                          to={`/users/${encodeURIComponent(user.id)}`}
                        >
                          查看详情
                        </Link>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="px-4 py-16 text-center text-sm text-muted-foreground">
                没有找到符合条件的用户。
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {query.data ? (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            共 {query.data.pagination.total} 个用户
          </span>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              <ChevronLeftIcon aria-hidden="true" />
              上一页
            </Button>
            <span>
              {page} / {Math.max(1, query.data.pagination.total_pages)}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page >= query.data.pagination.total_pages}
              onClick={() => setPage((value) => value + 1)}
            >
              下一页
              <ChevronRightIcon aria-hidden="true" />
            </Button>
          </div>
        </div>
      ) : null}

      <CreateUserSheet open={creating} onOpenChange={setCreating} />
    </div>
  )
}

function CreateUserSheet({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const mutation = useCreateUser()
  const [form, setForm] = useState({
    username: "",
    display_name: "",
    email: "",
    password: "",
  })

  const reset = () =>
    setForm({ username: "", display_name: "", email: "", password: "" })

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
      onSuccess: () => changeOpen(false),
      onSettled: () => setForm((value) => ({ ...value, password: "" })),
    })
  }

  return (
    <Sheet open={open} onOpenChange={changeOpen}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>新建内部用户</SheetTitle>
          <SheetDescription>
            创建人员账号后，再进入详情绑定钉钉或 ONES 身份。
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
