import { useState, type FormEvent } from "react"
import {
  ArrowLeftIcon,
  LoaderCircleIcon,
  SaveIcon,
  ShieldOffIcon,
} from "lucide-react"
import { Link, useParams, useSearchParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ExternalIdentityPanel } from "@/contexts/external-identities"
import {
  useUpdateUser,
  useUser,
} from "@/contexts/users/application/user-queries"
import type { User } from "@/contexts/users/domain/user"
import {
  ConfirmationSheet,
  Field,
  RequestError,
  UserStatusBadge,
} from "@/contexts/users/presentation/user-ui"
import { formatDate } from "@/contexts/users/presentation/format-date"
import { ApiError } from "@/shared/api/api-client"

export function UserDetailPage() {
  const { userId = "" } = useParams()
  const [searchParams] = useSearchParams()
  const candidateId = searchParams.get("candidate")?.trim() ?? ""
  const query = useUser(userId)

  if (query.isLoading) {
    return (
      <div className="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
        <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
        正在加载用户…
      </div>
    )
  }
  if (query.isError) {
    const missing =
      query.error instanceof ApiError && query.error.status === 404
    return (
      <div className="mx-auto max-w-3xl space-y-4 px-4 py-8">
        <h1 className="text-2xl font-semibold">
          {missing ? "用户不存在" : "无法加载用户"}
        </h1>
        <RequestError error={query.error} />
        <Link to="/users" className={buttonVariants({ variant: "outline" })}>
          返回用户列表
        </Link>
      </div>
    )
  }
  if (!query.data) return null

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <div>
        <Link
          to="/users"
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeftIcon aria-hidden="true" />
          返回用户列表
        </Link>
      </div>
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">
              {query.data.display_name}
            </h1>
            <UserStatusBadge status={query.data.status} />
            <Badge variant="outline">
              {query.data.account_type === "human" ? "人员账号" : "服务账号"}
            </Badge>
          </div>
          <p className="mt-2 font-mono text-xs text-muted-foreground">
            {query.data.username} · {query.data.id}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          更新于 {formatDate(query.data.updated_at)} · r{query.data.revision}
        </p>
      </header>

      <UserProfileCard key={query.data.revision} user={query.data} />
      <ExternalIdentityPanel
        user={query.data}
        discoveryCandidateId={candidateId}
      />
    </div>
  )
}

function UserProfileCard({ user }: { user: User }) {
  const update = useUpdateUser(user.id)
  const [displayName, setDisplayName] = useState(user.display_name)
  const [email, setEmail] = useState(user.email)
  const [confirmStatus, setConfirmStatus] = useState(false)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    update.mutate({
      expected_revision: user.revision,
      display_name: displayName,
      email,
      status: user.status,
    })
  }

  const toggleStatus = () => {
    const next = user.status === "enabled" ? "disabled" : "enabled"
    update.mutate(
      {
        expected_revision: user.revision,
        display_name: displayName,
        email,
        status: next,
      },
      { onSuccess: () => setConfirmStatus(false) }
    )
  }

  return (
    <Card className="shadow-none">
      <CardHeader className="border-b">
        <CardTitle>基本资料</CardTitle>
        <CardDescription>
          停用用户会撤销其管理会话，并阻止已绑定钉钉身份创建新任务。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={submit}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="显示名称" htmlFor="user-display-name">
              <Input
                id="user-display-name"
                required
                maxLength={200}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </Field>
            <Field label="邮箱" htmlFor="user-email">
              <Input
                id="user-email"
                type="email"
                maxLength={320}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </Field>
          </div>
          <RequestError error={update.error} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : (
                <SaveIcon aria-hidden="true" />
              )}
              保存资料
            </Button>
            <Button
              type="button"
              variant={user.status === "enabled" ? "destructive" : "outline"}
              disabled={update.isPending}
              onClick={() => setConfirmStatus(true)}
            >
              <ShieldOffIcon aria-hidden="true" />
              {user.status === "enabled" ? "停用用户" : "重新启用"}
            </Button>
          </div>
        </form>
      </CardContent>
      <ConfirmationSheet
        open={confirmStatus}
        onOpenChange={setConfirmStatus}
        title={user.status === "enabled" ? "停用用户" : "重新启用用户"}
        description={
          user.status === "enabled"
            ? `停用“${user.display_name}”会撤销其管理会话，并阻止其钉钉身份创建新任务。`
            : `重新启用“${user.display_name}”不会自动启用已停用或已解绑的外部身份。`
        }
        confirmLabel={user.status === "enabled" ? "确认停用" : "确认启用"}
        destructive={user.status === "enabled"}
        pending={update.isPending}
        onConfirm={toggleStatus}
      />
    </Card>
  )
}
