import { useState, type FormEvent } from "react"
import {
  ArrowLeftIcon,
  LoaderCircleIcon,
  SaveIcon,
  ShieldOffIcon,
  UsersRoundIcon,
} from "lucide-react"
import { Link, useParams } from "react-router-dom"

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
import { Checkbox } from "@/components/ui/checkbox"
import { ExternalIdentityPanel } from "@/contexts/external-identities"
import { useAdminCapabilitySummary } from "@/contexts/auth/application/admin-capability-query"
import {
  useUpdateUser,
  useUser,
} from "@/contexts/users/application/user-queries"
import type { User } from "@/contexts/users/domain/user"
import type { UserDetail } from "@/contexts/users/domain/user"
import {
  useRoles,
  useUpdateUserRoles,
} from "@/contexts/authorization/application/role-authorization-queries"
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
  const adminCapabilities = useAdminCapabilitySummary()
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
      <UserRolesCard
        key={`roles-${query.data.roles.map((role) => `${role.id}:${role.membership_revision}`).join(",")}`}
        user={query.data}
      />
      <ExternalIdentityPanel
        mode="admin"
        userId={query.data.id}
        canManage={Boolean(adminCapabilities.data?.capabilities.includes("users.manage"))}
      />
    </div>
  )
}

function UserRolesCard({ user }: { user: UserDetail }) {
  const roles = useRoles({ search: "", status: "enabled", origin: "" })
  const mutation = useUpdateUserRoles(user.id)
  const current = new Map(
    user.roles.map((role) => [
      role.id,
      {
        enabled: role.membership_status === "enabled",
        expires_at: role.expires_at ?? "",
      },
    ])
  )
  const [selection, setSelection] = useState(current)
  const changedRoles = (roles.data?.items ?? []).filter(
    (role) =>
      JSON.stringify(
        current.get(role.id) ?? { enabled: false, expires_at: "" }
      ) !==
      JSON.stringify(
        selection.get(role.id) ?? { enabled: false, expires_at: "" }
      )
  )

  const save = () =>
    mutation.mutate({
      confirmed: changedRoles.some((role) => role.protected),
      changes: changedRoles.map((role) => ({
        role_id: role.id,
        expected_role_revision: role.membership_revision,
        enabled: selection.get(role.id)?.enabled ?? false,
        expires_at: selection.get(role.id)?.expires_at || null,
      })),
    })

  return (
    <Card className="shadow-none">
      <CardHeader className="border-b">
        <CardTitle>角色与有效权限</CardTitle>
        <CardDescription>
          人员可以绑定多个角色；到期、停用的成员关系不会参与新的授权决策。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-2">
          {roles.data?.items.map((role) => {
            const selected = selection.get(role.id)
            return (
              <div key={role.id} className="rounded-lg border p-3">
                <label className="flex items-start gap-3">
                  <Checkbox
                    checked={Boolean(selected?.enabled)}
                    onCheckedChange={(checked) => {
                      const next = new Map(selection)
                      next.set(role.id, {
                        enabled: Boolean(checked),
                        expires_at: selected?.expires_at ?? "",
                      })
                      setSelection(next)
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2 font-medium">
                      {role.name}
                      {role.protected ? <Badge>系统角色</Badge> : null}
                    </span>
                    <span className="mt-1 block font-mono text-xs text-muted-foreground">
                      {role.code}
                    </span>
                  </span>
                </label>
                <Input
                  className="mt-3"
                  type="datetime-local"
                  aria-label={`${role.name}的角色失效时间`}
                  disabled={!selected?.enabled}
                  value={toLocalDateTime(selected?.expires_at ?? "")}
                  onChange={(event) => {
                    const next = new Map(selection)
                    next.set(role.id, {
                      enabled: true,
                      expires_at: event.target.value
                        ? new Date(event.target.value).toISOString()
                        : "",
                    })
                    setSelection(next)
                  }}
                />
              </div>
            )
          })}
        </div>
        <RequestError error={roles.error ?? mutation.error} />
        <Button
          disabled={changedRoles.length === 0 || mutation.isPending}
          onClick={save}
        >
          <UsersRoundIcon aria-hidden="true" />
          原子保存角色分配
        </Button>

        <div className="rounded-lg border bg-muted/30 p-4">
          <p className="font-medium">
            {user.authorization_summary.access_status}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            管理后台能力{" "}
            {user.authorization_summary.management_capabilities.length} 项 ·
            业务应用 {user.authorization_summary.business_applications.length}{" "}
            个
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {user.authorization_summary.business_applications.map(
              (application) => (
                <Badge key={application.id} variant="outline">
                  {application.name} · 来源{" "}
                  {application.source_role_codes.join("、")}
                </Badge>
              )
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function toLocalDateTime(value: string) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
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
