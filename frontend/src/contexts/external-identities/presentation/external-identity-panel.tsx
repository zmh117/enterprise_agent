import { useState, type FormEvent } from "react"
import {
  CheckCircle2Icon,
  ClipboardIcon,
  KeyRoundIcon,
  Link2Icon,
  LoaderCircleIcon,
  RefreshCwIcon,
  UnlinkIcon,
} from "lucide-react"
import { toast } from "sonner"

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
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  useBeginSelfDingTalkBinding,
  useBeginSelfOnesBinding,
  useChangeSelfOnesDefaultTeam,
  useConfirmSelfOnesBinding,
  useSelfExternalIdentities,
  useUnbindSelfOnesBinding,
} from "@/contexts/external-identities/application/external-identity-queries"
import type {
  DingTalkBindingChallenge,
  OnesBindingChallenge,
  SelfDingTalkIdentity,
  SelfOnesIdentity,
} from "@/contexts/external-identities/domain/external-identity"
import { ApiError } from "@/shared/api/api-client"

export function ExternalIdentityPanel() {
  const overview = useSelfExternalIdentities()
  const unbind = useUnbindSelfOnesBinding()
  const dingTalkChallenge = useBeginSelfDingTalkBinding()
  const [binding, setBinding] = useState(false)
  const [confirmUnbind, setConfirmUnbind] = useState(false)
  const ones = overview.data?.ones ?? null

  return (
    <Card className="shadow-none">
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>统一身份</CardTitle>
            <CardDescription className="mt-1">
              钉钉主体来自受信消息；ONES 密码只参与一次登录请求，不会保存。
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => void overview.refetch()}
            disabled={overview.isFetching}
          >
            <RefreshCwIcon
              className={overview.isFetching ? "animate-spin" : ""}
              aria-hidden="true"
            />
            刷新状态
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {overview.isLoading ? <Loading label="正在加载本人身份…" /> : null}
        <ErrorMessage error={overview.error || unbind.error} />

        <section className="space-y-3 rounded-xl border bg-muted/20 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="font-medium">钉钉本人身份</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                创建一次性口令后，请用自己的钉钉账号发给已接入的企业机器人。
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              onClick={() => dingTalkChallenge.mutate()}
              disabled={dingTalkChallenge.isPending}
            >
              <Link2Icon aria-hidden="true" />
              创建绑定口令
            </Button>
          </div>
          <ErrorMessage error={dingTalkChallenge.error} />
          {dingTalkChallenge.data ? (
            <DingTalkChallenge challenge={dingTalkChallenge.data} />
          ) : null}
          {overview.data?.dingtalk.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {overview.data.dingtalk.map((identity) => (
                <DingTalkIdentityCard
                  key={`${identity.enterprise?.corp_id}:${identity.staff_id}`}
                  identity={identity}
                />
              ))}
            </div>
          ) : (
            !overview.isLoading && (
              <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                尚未绑定钉钉身份。
              </p>
            )
          )}
        </section>

        <section className="space-y-4 rounded-xl border bg-muted/20 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="font-medium">ONES 本人身份</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Agent 仅能通过与你本人绑定的凭据和默认 Team 调用 ONES MCP。
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setBinding(true)}
              disabled={overview.isLoading || overview.isError}
            >
              <KeyRoundIcon aria-hidden="true" />
              {ones ? "重新验证" : "验证 ONES"}
            </Button>
          </div>
          {ones ? (
            <OnesIdentityCard
              identity={ones}
              onUnbind={() => setConfirmUnbind(true)}
            />
          ) : (
            <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              尚未验证 ONES。验证成功并选择默认 Team 后才会签发调用资格。
            </p>
          )}
        </section>
      </CardContent>

      <OnesBindingSheet
        open={binding}
        onOpenChange={setBinding}
        hasExisting={Boolean(ones)}
      />
      <AlertDialog open={confirmUnbind} onOpenChange={setConfirmUnbind}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>解绑本人 ONES？</AlertDialogTitle>
            <AlertDialogDescription>
              当前个人凭据会立即失效；之后必须重新验证才能调用 ONES MCP。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={unbind.isPending}>取消</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={unbind.isPending}
              onClick={() =>
                unbind.mutate(undefined, {
                  onSuccess: () => setConfirmUnbind(false),
                })
              }
            >
              <UnlinkIcon aria-hidden="true" />
              确认解绑
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

function DingTalkChallenge({
  challenge,
}: {
  challenge: DingTalkBindingChallenge
}) {
  const copy = async () => {
    await navigator.clipboard.writeText(challenge.code)
    toast.success("绑定口令已复制")
  }
  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-950">
      <p className="font-medium">一次性绑定口令</p>
      <div className="mt-2 flex min-w-0 items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded bg-white px-3 py-2 text-xs">
          {challenge.code}
        </code>
        <Button type="button" size="icon" variant="outline" onClick={copy}>
          <ClipboardIcon aria-hidden="true" />
          <span className="sr-only">复制绑定口令</span>
        </Button>
      </div>
      <p className="mt-2 text-xs">
        有效期至 {formatDate(challenge.expires_at)}。口令只能消费一次，刷新身份状态即可查看结果。
      </p>
    </div>
  )
}

function DingTalkIdentityCard({
  identity,
}: {
  identity: SelfDingTalkIdentity
}) {
  return (
    <article className="rounded-lg border bg-background p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium">{identity.nickname || "钉钉用户"}</p>
        <Badge variant={identity.status === "enabled" ? "secondary" : "outline"}>
          {identity.status === "enabled" ? "已启用" : "已停用"}
        </Badge>
      </div>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <Fact label="企业" value={identity.enterprise?.name || "不可用"} />
        <Fact label="最近使用" value={formatDate(identity.last_used_at)} />
      </dl>
    </article>
  )
}

function OnesIdentityCard({
  identity,
  onUnbind,
}: {
  identity: SelfOnesIdentity
  onUnbind: () => void
}) {
  const changeTeam = useChangeSelfOnesDefaultTeam()
  const [teamId, setTeamId] = useState(identity.default_team?.id ?? "")
  const saveTeam = () =>
    changeTeam.mutate(
      {
        default_team_id: teamId,
        expected_identity_revision: identity.identity_revision,
      },
      { onSuccess: () => toast.success("默认 Team 已更新") }
    )
  return (
    <article className="rounded-lg border bg-background p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <CheckCircle2Icon className="size-4 text-emerald-600" aria-hidden="true" />
          <p className="font-medium">{identity.user_name}</p>
        </div>
        <Badge variant={identity.availability === "AVAILABLE" ? "secondary" : "outline"}>
          {availabilityLabel(identity.availability)}
        </Badge>
      </div>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <Fact label="最近验证" value={formatDate(identity.verified_at)} />
        <Fact label="最近成功调用" value={formatDate(identity.last_success_at)} />
      </dl>
      <div className="mt-4 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <div className="space-y-1.5">
          <Label htmlFor="default-team">默认 Team</Label>
          <select
            id="default-team"
            className="h-9 w-full rounded-lg border bg-background px-3 text-sm"
            value={teamId}
            onChange={(event) => setTeamId(event.target.value)}
          >
            {identity.teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name || team.id}
              </option>
            ))}
          </select>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={saveTeam}
          disabled={
            changeTeam.isPending ||
            !teamId ||
            teamId === identity.default_team?.id
          }
        >
          保存默认 Team
        </Button>
      </div>
      <ErrorMessage error={changeTeam.error} />
      <Button
        type="button"
        size="sm"
        variant="destructive"
        className="mt-4"
        onClick={onUnbind}
      >
        <UnlinkIcon aria-hidden="true" />
        解绑 ONES
      </Button>
    </article>
  )
}

function OnesBindingSheet({
  open,
  onOpenChange,
  hasExisting,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  hasExisting: boolean
}) {
  const begin = useBeginSelfOnesBinding()
  const confirm = useConfirmSelfOnesBinding()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [challenge, setChallenge] = useState<OnesBindingChallenge | null>(null)
  const [teamId, setTeamId] = useState("")
  const [replaceExisting, setReplaceExisting] = useState(false)

  const reset = () => {
    setEmail("")
    setPassword("")
    setChallenge(null)
    setTeamId("")
    setReplaceExisting(false)
    begin.reset()
    confirm.reset()
  }
  const changeOpen = (next: boolean) => {
    if (!next) reset()
    onOpenChange(next)
  }
  const verify = async (event: FormEvent) => {
    event.preventDefault()
    try {
      const next = await begin.mutateAsync({ email: email.trim(), password })
      setChallenge(next)
      setTeamId(next.teams[0]?.id ?? "")
    } catch {
      // Safe API error is rendered below.
    } finally {
      setPassword("")
    }
  }
  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!challenge) return
    await confirm.mutateAsync({
      challenge_id: challenge.id,
      default_team_id: teamId,
      replace_existing: replaceExisting,
    })
    toast.success("ONES 身份已验证")
    changeOpen(false)
  }

  return (
    <Sheet open={open} onOpenChange={changeOpen}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{hasExisting ? "重新验证 ONES" : "验证 ONES"}</SheetTitle>
          <SheetDescription>
            邮箱和密码仅发送给受信 ONES Provider。浏览器和平台都不会展示返回 Token。
          </SheetDescription>
        </SheetHeader>
        {!challenge ? (
          <form className="space-y-4 px-4" onSubmit={verify}>
            <div className="space-y-2">
              <Label htmlFor="ones-email">ONES 邮箱</Label>
              <Input
                id="ones-email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ones-password">一次性验证密码</Label>
              <Input
                id="ones-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <ErrorMessage error={begin.error} />
            <SheetFooter className="px-0">
              <Button type="submit" disabled={begin.isPending}>
                {begin.isPending ? <LoaderCircleIcon className="animate-spin" /> : null}
                验证并读取 Team
              </Button>
            </SheetFooter>
          </form>
        ) : (
          <form className="space-y-4 px-4" onSubmit={save}>
            <div className="rounded-lg border bg-muted/20 p-4 text-sm">
              <p className="font-medium">{challenge.display_name}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                已验证 ONES 账号；请选择本次绑定的默认 Team。
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ones-team">默认 Team</Label>
              <select
                id="ones-team"
                required
                className="h-9 w-full rounded-lg border bg-background px-3 text-sm"
                value={teamId}
                onChange={(event) => setTeamId(event.target.value)}
              >
                {challenge.teams.map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.name || team.id}
                  </option>
                ))}
              </select>
            </div>
            {hasExisting ? (
              <label className="flex items-start gap-2 rounded-lg border p-3 text-sm">
                <Checkbox
                  checked={replaceExisting}
                  onCheckedChange={(checked) => setReplaceExisting(Boolean(checked))}
                />
                <span>若这是另一个 ONES 账号，确认替换当前绑定。</span>
              </label>
            ) : null}
            <ErrorMessage error={confirm.error} />
            <SheetFooter className="px-0">
              <Button type="submit" disabled={confirm.isPending || !teamId}>
                保存绑定
              </Button>
              <Button type="button" variant="outline" onClick={() => setChallenge(null)}>
                返回重试
              </Button>
            </SheetFooter>
          </form>
        )}
      </SheetContent>
    </Sheet>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-all">{value || "—"}</dd>
    </div>
  )
}

function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <p role="alert" className="mt-3 text-sm text-destructive">
      {error instanceof ApiError ? error.message : "请求失败，请稍后重试。"}
    </p>
  )
}

function Loading({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
      <LoaderCircleIcon className="size-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  )
}

function availabilityLabel(value: SelfOnesIdentity["availability"]) {
  return {
    AVAILABLE: "可用",
    REVERIFY_REQUIRED: "需要重新验证",
    ADMIN_DISABLED: "已停用",
    UNBOUND: "未绑定",
  }[value]
}

function formatDate(value?: string | null) {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN")
}
