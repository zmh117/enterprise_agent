import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { KeyRoundIcon, LoaderCircleIcon, RefreshCwIcon, ShieldIcon } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  changePassword,
  listSessions,
  revokeSession,
} from "@/contexts/auth/infrastructure/auth-api"
import { ApiError } from "@/shared/api/api-client"

const sessionsKey = ["account", "sessions"] as const

export function AccountSecurityPage() {
  const sessions = useQuery({ queryKey: sessionsKey, queryFn: listSessions })
  const client = useQueryClient()
  const revoke = useMutation({
    mutationFn: revokeSession,
    onSuccess: () => client.invalidateQueries({ queryKey: sessionsKey }),
  })
  return (
    <main className="mx-auto w-full max-w-[1000px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <div className="flex items-center gap-2 text-xs font-medium text-indigo-700">
          <ShieldIcon className="size-4" aria-hidden="true" />
          账户安全
        </div>
        <h1 className="mt-2 text-2xl font-semibold">密码与会话</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          修改本地系统密码，并撤销不再使用的登录会话。
        </p>
      </header>
      <PasswordCard />
      <Card className="shadow-none">
        <CardHeader className="flex-row items-start justify-between gap-3">
          <div>
            <CardTitle>登录会话</CardTitle>
            <CardDescription className="mt-1">这里只显示当前系统账户自己的会话。</CardDescription>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void sessions.refetch()}
            disabled={sessions.isFetching}
          >
            <RefreshCwIcon className={sessions.isFetching ? "animate-spin" : ""} />
            刷新
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <ErrorMessage error={sessions.error || revoke.error} />
          {sessions.data?.map((session) => (
            <article
              key={session.id}
              className="grid gap-3 rounded-lg border p-4 text-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
            >
              <div className="min-w-0">
                <p className="truncate font-medium">
                  {session.user_agent_summary || "未知客户端"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {session.remote_address_summary || "地址不可用"} · 最近活动 {formatDate(session.last_seen_at)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  状态 {session.status} · 绝对过期 {formatDate(session.absolute_expires_at)}
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={session.status !== "active" || revoke.isPending}
                onClick={() => revoke.mutate(session.id)}
              >
                撤销
              </Button>
            </article>
          ))}
          {sessions.isLoading ? (
            <p className="text-sm text-muted-foreground">正在加载会话…</p>
          ) : null}
        </CardContent>
      </Card>
    </main>
  )
}

function PasswordCard() {
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const mutation = useMutation({
    mutationFn: () => changePassword(currentPassword, newPassword),
  })
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (newPassword !== confirmation) return
    try {
      await mutation.mutateAsync()
      setCurrentPassword("")
      setNewPassword("")
      setConfirmation("")
      toast.success("密码已更新")
    } catch {
      // Safe API error is rendered below.
    }
  }
  const mismatch = Boolean(confirmation) && newPassword !== confirmation
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRoundIcon className="size-4" />
          修改密码
        </CardTitle>
        <CardDescription>新密码至少 12 个字符。</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="grid gap-4 sm:grid-cols-3" onSubmit={submit}>
          <PasswordField id="current-password" label="当前密码" value={currentPassword} setValue={setCurrentPassword} />
          <PasswordField id="new-password" label="新密码" value={newPassword} setValue={setNewPassword} minLength={12} />
          <PasswordField id="confirm-password" label="确认新密码" value={confirmation} setValue={setConfirmation} minLength={12} />
          <div className="sm:col-span-3">
            {mismatch ? <p role="alert" className="mb-3 text-sm text-destructive">两次输入的新密码不一致。</p> : null}
            <ErrorMessage error={mutation.error} />
            <Button type="submit" disabled={mutation.isPending || mismatch}>
              {mutation.isPending ? <LoaderCircleIcon className="animate-spin" /> : null}
              更新密码
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function PasswordField({
  id,
  label,
  value,
  setValue,
  minLength,
}: {
  id: string
  label: string
  value: string
  setValue: (value: string) => void
  minLength?: number
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="password"
        autoComplete={id === "current-password" ? "current-password" : "new-password"}
        required
        minLength={minLength}
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
    </div>
  )
}

function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <p role="alert" className="mb-3 text-sm text-destructive">
      {error instanceof ApiError ? error.message : "请求失败，请稍后重试。"}
    </p>
  )
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN")
}
