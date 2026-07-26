import { useState, type FormEvent } from "react"
import { useQueryClient } from "@tanstack/react-query"
import {
  KeyRoundIcon,
  Link2Icon,
  LoaderCircleIcon,
  PlusIcon,
  UnlinkIcon,
} from "lucide-react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  useBindDingTalkIdentity,
  useDingTalkTenants,
  useExternalIdentities,
  useIdentityProviders,
  useUnbindIdentity,
  useUpdateIdentityStatus,
  externalIdentityKeys,
  verifyAndBindOnesIdentity,
} from "@/contexts/external-identities/application/external-identity-queries"
import type {
  DingTalkTenant,
  ExternalIdentity,
} from "@/contexts/external-identities/domain/external-identity"
import type { User } from "@/contexts/users/domain/user"
import {
  useBindDingTalkIdentityCandidate,
  useDingTalkIdentityCandidate,
} from "@/contexts/dingtalk-identity-discovery/application/dingtalk-identity-candidate-queries"
import type { DingTalkIdentityCandidate } from "@/contexts/dingtalk-identity-discovery/domain/dingtalk-identity-candidate"
import {
  ConfirmationSheet,
  Field,
  RequestError,
} from "@/contexts/users/presentation/user-ui"
import { formatDate } from "@/contexts/users/presentation/format-date"
import { useRoles } from "@/contexts/authorization/application/role-authorization-queries"

export function ExternalIdentityPanel({
  user,
  discoveryCandidateId = "",
}: {
  user: User
  discoveryCandidateId?: string
}) {
  const identities = useExternalIdentities(user.id)
  const providers = useIdentityProviders()
  const tenants = useDingTalkTenants()
  const candidate = useDingTalkIdentityCandidate(discoveryCandidateId)
  const [binding, setBinding] = useState<"dingtalk" | "ones" | null>(null)
  const [candidateDismissed, setCandidateDismissed] = useState(false)
  const canBind = user.account_type === "human" && user.status === "enabled"
  const dingtalkAvailable =
    providers.data?.find((item) => item.code === "dingtalk")?.available &&
    Boolean(tenants.data?.length)
  const onesProvider = providers.data?.find((item) => item.code === "ones")

  return (
    <Card className="shadow-none">
      <CardHeader className="border-b">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>外部身份</CardTitle>
            <CardDescription className="mt-1">
              只支持钉钉和 ONES。身份映射不会自动授予角色、能力或 ONES
              业务权限。
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!canBind || !dingtalkAvailable}
              onClick={() => setBinding("dingtalk")}
            >
              <PlusIcon aria-hidden="true" />
              绑定钉钉
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!canBind || !onesProvider?.available}
              onClick={() => setBinding("ones")}
            >
              <PlusIcon aria-hidden="true" />
              绑定 ONES
            </Button>
          </div>
        </div>
        {!canBind ? (
          <p className="mt-2 text-xs text-amber-700">
            {user.account_type === "service"
              ? "服务账号不能绑定个人外部身份。"
              : "请先启用该用户，再绑定外部身份。"}
          </p>
        ) : null}
      </CardHeader>
      <CardContent>
        {discoveryCandidateId &&
        candidate.data?.identity_state === "restore_required" ? (
          <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm">
            <div className="font-medium text-amber-900">恢复历史钉钉身份</div>
            <p className="mt-1 text-amber-800">
              此身份原属于当前人员。请先确保人员已启用，再在下方找到对应钉钉身份并点击“恢复身份”。
            </p>
          </div>
        ) : null}
        {candidate.isError ? <RequestError error={candidate.error} /> : null}
        {identities.isLoading || providers.isLoading || tenants.isLoading ? (
          <div className="flex min-h-28 items-center justify-center gap-2 text-sm text-muted-foreground">
            <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
            正在加载身份…
          </div>
        ) : null}
        <RequestError
          error={identities.error || providers.error || tenants.error}
        />
        {identities.data && identities.data.length === 0 ? (
          <div className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
            该用户尚未绑定钉钉或 ONES 身份。
          </div>
        ) : null}
        {identities.data && identities.data.length > 0 ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {identities.data.map((identity) => (
              <IdentityCard
                key={identity.id}
                identity={identity}
                userId={user.id}
                discoveryCandidate={candidate.data ?? null}
              />
            ))}
          </div>
        ) : null}
      </CardContent>

      <DingTalkBindingSheet
        open={binding === "dingtalk"}
        onOpenChange={(open) => setBinding(open ? "dingtalk" : null)}
        user={user}
        tenants={tenants.data ?? []}
      />
      <CandidateDingTalkBindingSheet
        open={
          !candidateDismissed &&
          candidate.data?.identity_state === "waiting_bind"
        }
        onOpenChange={(open) => {
          if (!open) setCandidateDismissed(true)
        }}
        user={user}
        candidateId={discoveryCandidateId}
      />
      <OnesBindingSheet
        open={binding === "ones"}
        onOpenChange={(open) => setBinding(open ? "ones" : null)}
        user={user}
        instanceName={onesProvider?.display_name ?? "ONES"}
      />
    </Card>
  )
}

function IdentityCard({
  identity,
  userId,
  discoveryCandidate,
}: {
  identity: ExternalIdentity
  userId: string
  discoveryCandidate: DingTalkIdentityCandidate | null
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const updateStatus = useUpdateIdentityStatus(userId)
  const unbind = useUnbindIdentity(userId)
  const [confirmUnbind, setConfirmUnbind] = useState(false)
  const statusLabel = {
    enabled: "已启用",
    disabled: "已停用",
    unbound: "已解绑",
  }[identity.status]
  const nextStatus = identity.status === "enabled" ? "disabled" : "enabled"

  const changeStatus = () => {
    updateStatus.mutate(
      {
        identityId: identity.id,
        expectedRevision: identity.revision,
        status: nextStatus,
      },
      {
        onSuccess: async () => {
          const matchesCandidate =
            nextStatus === "enabled" &&
            discoveryCandidate?.identity_state === "restore_required" &&
            identity.provider === "dingtalk" &&
            identity.tenant_code === discoveryCandidate.tenant_code &&
            identity.external_subject_id ===
              discoveryCandidate.external_subject_id
          if (matchesCandidate) {
            await queryClient.invalidateQueries({
              queryKey: ["dingtalk-identity-candidates"],
            })
            toast.success("钉钉身份已恢复")
            navigate("/users/dingtalk-discovery")
          }
        },
      }
    )
  }

  const remove = () => {
    unbind.mutate(
      {
        identityId: identity.id,
        expectedRevision: identity.revision,
      },
      { onSuccess: () => setConfirmUnbind(false) }
    )
  }

  return (
    <article className="rounded-xl border bg-muted/20 p-4">
      <div className="flex items-start justify-between gap-3">
        <span className="flex size-9 items-center justify-center rounded-lg bg-background ring-1 ring-border">
          {identity.provider === "dingtalk" ? (
            <Link2Icon className="size-4 text-blue-600" aria-hidden="true" />
          ) : (
            <KeyRoundIcon
              className="size-4 text-indigo-600"
              aria-hidden="true"
            />
          )}
        </span>
        <Badge
          variant={identity.status === "enabled" ? "secondary" : "outline"}
        >
          {statusLabel}
        </Badge>
      </div>
      <h3 className="mt-3 font-semibold">
        {identity.provider === "dingtalk" ? "钉钉身份" : "ONES 身份"}
      </h3>
      <p className="mt-1 text-sm">
        {identity.display_name || "未设置展示名称"}
      </p>
      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
        <IdentityField label="租户 / 实例" value={identity.tenant_code} />
        <IdentityField
          label="外部主体"
          value={identity.external_subject_id}
          mono
        />
        <IdentityField
          label="连接器"
          value={identity.connector_id || "服务端 ONES 实例"}
        />
        <IdentityField
          label="验证时间"
          value={formatDate(identity.verified_at)}
        />
        <IdentityField
          label="最近使用"
          value={formatDate(identity.last_seen_at)}
        />
        <IdentityField label="修订" value={`r${identity.revision}`} />
      </dl>
      {identity.provider === "ones" && identity.metadata.team_uuids?.length ? (
        <div className="mt-3 flex flex-wrap gap-1">
          {identity.metadata.team_uuids.map((team) => (
            <Badge
              key={team}
              variant="outline"
              className="font-mono font-normal"
            >
              {team}
            </Badge>
          ))}
        </div>
      ) : null}
      <RequestError error={updateStatus.error || unbind.error} />
      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={updateStatus.isPending || unbind.isPending}
          onClick={changeStatus}
        >
          {identity.status === "enabled"
            ? "停用身份"
            : identity.status === "unbound"
              ? "恢复身份"
              : "启用身份"}
        </Button>
        {identity.status !== "unbound" ? (
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={updateStatus.isPending || unbind.isPending}
            onClick={() => setConfirmUnbind(true)}
          >
            <UnlinkIcon aria-hidden="true" />
            解绑
          </Button>
        ) : null}
      </div>
      <ConfirmationSheet
        open={confirmUnbind}
        onOpenChange={setConfirmUnbind}
        title={`解绑${identity.provider === "dingtalk" ? "钉钉" : "ONES"}身份`}
        description="解绑会保留审计历史并停止身份解析；不会把该身份自动转移给其他用户。"
        confirmLabel="确认解绑"
        destructive
        pending={unbind.isPending}
        onConfirm={remove}
      />
    </article>
  )
}

function CandidateDingTalkBindingSheet({
  open,
  onOpenChange,
  user,
  candidateId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User
  candidateId: string
}) {
  const navigate = useNavigate()
  const candidate = useDingTalkIdentityCandidate(candidateId)
  const mutation = useBindDingTalkIdentityCandidate(candidateId, user.id)
  const roles = useRoles({ search: "", status: "enabled", origin: "" })
  const [initialRoleIds, setInitialRoleIds] = useState<Set<string>>(new Set())
  const [bindOnly, setBindOnly] = useState(false)

  const changeOpen = (next: boolean) => {
    if (!next) mutation.reset()
    onOpenChange(next)
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!candidate.data) return
    mutation.mutate(
      {
        target_user_id: user.id,
        expected_candidate_revision: candidate.data.revision,
        expected_user_revision: user.revision,
        initial_role_ids: [...initialRoleIds],
        bind_without_access_confirmed: bindOnly,
      },
      {
        onSuccess: () => {
          toast.success("钉钉用户已绑定")
          navigate("/users/dingtalk-discovery")
        },
      }
    )
  }

  return (
    <Sheet open={open} onOpenChange={changeOpen}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>确认绑定钉钉用户</SheetTitle>
          <SheetDescription>
            身份来源字段由服务端候选记录确定，不可在客户端修改。
          </SheetDescription>
        </SheetHeader>
        {candidate.isLoading ? (
          <div className="flex items-center gap-2 px-4 text-sm text-muted-foreground">
            <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
            正在加载候选信息…
          </div>
        ) : null}
        {candidate.data ? (
          <form className="space-y-4 px-4" onSubmit={submit}>
            <dl className="grid gap-4 rounded-lg border bg-muted/20 p-4 text-sm">
              <IdentityField
                label="钉钉企业"
                value={candidate.data.tenant_code}
              />
              <IdentityField
                label="连接器"
                value={
                  candidate.data.latest_message?.connector_name ||
                  candidate.data.latest_message?.connector_id ||
                  "连接器名称不可用"
                }
              />
              <IdentityField
                label="钉钉用户 ID"
                value={candidate.data.external_subject_id}
                mono
              />
              <IdentityField
                label="钉钉用户名"
                value={candidate.data.display_name || "未提供钉钉用户名"}
              />
              <IdentityField
                label="目标人员"
                value={`${user.display_name}（${user.username}）`}
              />
            </dl>
            <div className="space-y-3 rounded-lg border p-4">
              <div>
                <h3 className="text-sm font-medium">初始角色</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  身份绑定和全部初始角色会在同一个事务中完成；任一角色失败会整体回滚。
                </p>
              </div>
              <div className="grid gap-2">
                {roles.data?.items.map((role) => (
                  <label
                    key={role.id}
                    className="flex items-center gap-2 rounded-md border p-3 text-sm"
                  >
                    <Checkbox
                      checked={initialRoleIds.has(role.id)}
                      disabled={bindOnly}
                      onCheckedChange={(checked) => {
                        const next = new Set(initialRoleIds)
                        if (checked) next.add(role.id)
                        else next.delete(role.id)
                        setInitialRoleIds(next)
                      }}
                    />
                    <span>
                      {role.name}
                      <span className="ml-2 font-mono text-xs text-muted-foreground">
                        {role.code}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
              <label className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-sm">
                <Checkbox
                  checked={bindOnly}
                  disabled={initialRoleIds.size > 0}
                  onCheckedChange={(checked) => setBindOnly(Boolean(checked))}
                />
                <span>
                  <span className="font-medium">仅绑定身份，暂不授权</span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    绑定后候选会立即消失，但该用户会显示“未获得应用权限”。
                  </span>
                </span>
              </label>
            </div>
            <RequestError error={roles.error} />
            <RequestError error={mutation.error} />
            <SheetFooter className="px-0">
              <Button
                type="submit"
                disabled={
                  mutation.isPending ||
                  user.account_type !== "human" ||
                  user.status !== "enabled" ||
                  (initialRoleIds.size === 0 && !bindOnly)
                }
              >
                {mutation.isPending ? (
                  <LoaderCircleIcon
                    className="animate-spin"
                    aria-hidden="true"
                  />
                ) : null}
                确认绑定并保存授权
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
        ) : null}
        {candidate.isError ? (
          <div className="px-4">
            <RequestError error={candidate.error} />
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}

function DingTalkBindingSheet({
  open,
  onOpenChange,
  user,
  tenants,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User
  tenants: DingTalkTenant[]
}) {
  const mutation = useBindDingTalkIdentity(user.id)
  const [connectorId, setConnectorId] = useState("")
  const [subjectId, setSubjectId] = useState("")
  const [displayName, setDisplayName] = useState("")

  const reset = () => {
    setConnectorId("")
    setSubjectId("")
    setDisplayName("")
    mutation.reset()
  }
  const changeOpen = (next: boolean) => {
    if (!next) reset()
    onOpenChange(next)
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const tenant = tenants.find((item) => item.connector_id === connectorId)
    if (!tenant) return
    mutation.mutate(
      {
        expected_user_revision: user.revision,
        tenant_code: tenant.tenant_code,
        external_subject_id: subjectId.trim(),
        connector_id: tenant.connector_id,
        display_name: displayName.trim(),
      },
      { onSuccess: () => changeOpen(false) }
    )
  }

  return (
    <Sheet open={open} onOpenChange={changeOpen}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>绑定钉钉身份</SheetTitle>
          <SheetDescription>
            只能选择已配置的受信钉钉 Stream 连接器。
          </SheetDescription>
        </SheetHeader>
        <form className="space-y-4 px-4" onSubmit={submit}>
          <Field label="钉钉租户 / 连接器" htmlFor="dingtalk-connector">
            <select
              id="dingtalk-connector"
              required
              className="h-8 w-full rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              value={connectorId}
              onChange={(event) => setConnectorId(event.target.value)}
            >
              <option value="">请选择连接器</option>
              {tenants.map((tenant) => (
                <option key={tenant.connector_id} value={tenant.connector_id}>
                  {tenant.name} · {tenant.tenant_code}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="senderStaffId"
            htmlFor="dingtalk-subject"
            hint="请输入钉钉事件中的稳定 senderStaffId，不按昵称自动匹配。"
          >
            <Input
              id="dingtalk-subject"
              required
              maxLength={200}
              value={subjectId}
              onChange={(event) => setSubjectId(event.target.value)}
            />
          </Field>
          <Field label="展示名称（可选）" htmlFor="dingtalk-display-name">
            <Input
              id="dingtalk-display-name"
              maxLength={200}
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </Field>
          <RequestError error={mutation.error} />
          <SheetFooter className="px-0">
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : null}
              绑定钉钉
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

function OnesBindingSheet({
  open,
  onOpenChange,
  user,
  instanceName,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User
  instanceName: string
}) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const reset = () => {
    setEmail("")
    setPassword("")
    setError(null)
  }
  const changeOpen = (next: boolean) => {
    if (!next) reset()
    onOpenChange(next)
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await verifyAndBindOnesIdentity(user.id, {
        expected_user_revision: user.revision,
        email: email.trim(),
        password,
      })
      await queryClient.invalidateQueries({
        queryKey: externalIdentityKeys.user(user.id),
      })
      changeOpen(false)
    } catch (caught) {
      setError(caught)
    } finally {
      setPassword("")
      setSubmitting(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={changeOpen}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>绑定 {instanceName} 身份</SheetTitle>
          <SheetDescription>
            邮箱和密码只用于本次服务端验证。系统不会保存密码、Token 或原始响应。
          </SheetDescription>
        </SheetHeader>
        <form className="space-y-4 px-4" onSubmit={submit}>
          <Field label="ONES 邮箱" htmlFor="ones-email">
            <Input
              id="ones-email"
              type="email"
              required
              maxLength={320}
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          <Field
            label="一次性验证密码"
            htmlFor="ones-password"
            hint="请求结束后立即从页面状态清除。"
          >
            <Input
              id="ones-password"
              type="password"
              required
              maxLength={512}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          <RequestError error={error} />
          <SheetFooter className="px-0">
            <Button type="submit" disabled={submitting}>
              {submitting ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : null}
              验证并绑定
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

function IdentityField({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={`mt-1 break-all ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  )
}
