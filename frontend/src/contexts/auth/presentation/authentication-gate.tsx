import { type FormEvent, type ReactNode, useEffect, useState } from "react"
import {
  BotIcon,
  LoaderCircleIcon,
  LogInIcon,
  RefreshCwIcon,
} from "lucide-react"

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
import type { AuthenticatedUser } from "@/contexts/auth/domain/authenticated-user"
import { getCurrentUser, login } from "@/contexts/auth/infrastructure/auth-api"
import { ApiError } from "@/shared/api/api-client"

type AuthenticationState =
  | { status: "checking" }
  | { status: "anonymous" }
  | { status: "authenticated"; user: AuthenticatedUser }
  | { status: "unavailable"; message: string }

export function AuthenticationGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthenticationState>({
    status: "checking",
  })

  const checkSession = async () => {
    setState({ status: "checking" })
    setState(await resolveAuthenticationState())
  }

  useEffect(() => {
    let active = true
    void resolveAuthenticationState().then((nextState) => {
      if (active) setState(nextState)
    })
    return () => {
      active = false
    }
  }, [])

  if (state.status === "checking") {
    return (
      <AuthenticationFrame>
        <LoaderCircleIcon className="size-6 animate-spin text-indigo-600" />
        <p className="text-sm text-muted-foreground">正在确认管理会话…</p>
      </AuthenticationFrame>
    )
  }

  if (state.status === "unavailable") {
    return (
      <AuthenticationFrame>
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>认证服务不可用</CardTitle>
            <CardDescription>{state.message}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button className="w-full" onClick={() => void checkSession()}>
              <RefreshCwIcon aria-hidden="true" />
              重新连接
            </Button>
          </CardContent>
        </Card>
      </AuthenticationFrame>
    )
  }

  if (state.status === "anonymous") {
    return (
      <LoginCard
        onAuthenticated={(user) => setState({ status: "authenticated", user })}
      />
    )
  }

  return children
}

function LoginCard({
  onAuthenticated,
}: {
  onAuthenticated: (user: AuthenticatedUser) => void
}) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState("")

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setErrorMessage("")
    try {
      const response = await login(username.trim(), password)
      onAuthenticated(response.user)
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "登录失败，请检查账号和密码。"
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthenticationFrame>
      <Card className="w-full max-w-md shadow-xl shadow-slate-950/5">
        <CardHeader className="space-y-4">
          <div className="flex size-11 items-center justify-center rounded-xl bg-indigo-600 text-white">
            <BotIcon className="size-6" aria-hidden="true" />
          </div>
          <div>
            <CardTitle className="text-xl">
              <h1>登录 Agent 应用平台</h1>
            </CardTitle>
            <CardDescription className="mt-1.5">
              使用系统账号建立受 RBAC 保护的管理会话。
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-2">
              <Label htmlFor="admin-username">用户名</Label>
              <Input
                id="admin-username"
                name="username"
                autoComplete="username"
                autoFocus
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="admin-password">密码</Label>
              <Input
                id="admin-password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            {errorMessage ? (
              <p role="alert" className="text-sm text-destructive">
                {errorMessage}
              </p>
            ) : null}
            <Button className="w-full" type="submit" disabled={submitting}>
              {submitting ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : (
                <LogInIcon aria-hidden="true" />
              )}
              {submitting ? "正在登录…" : "登录"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </AuthenticationFrame>
  )
}

function AuthenticationFrame({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-svh items-center justify-center bg-[radial-gradient(circle_at_top,_var(--color-indigo-100),_transparent_38%),linear-gradient(to_bottom,_white,_var(--color-slate-50))] p-6">
      <div className="flex w-full flex-col items-center gap-3">{children}</div>
    </main>
  )
}

async function resolveAuthenticationState(): Promise<AuthenticationState> {
  try {
    const response = await getCurrentUser()
    return { status: "authenticated", user: response.user }
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return { status: "anonymous" }
    }
    return {
      status: "unavailable",
      message:
        error instanceof Error
          ? error.message
          : "认证服务当前不可用，请稍后重试。",
    }
  }
}
