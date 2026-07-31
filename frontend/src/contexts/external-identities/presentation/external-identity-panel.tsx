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
  useAdminOnesCredential,
  useBeginSelfOnesBinding,
  useConfirmSelfOnesBinding,
  useDisableAdminOnesCredential,
  useDingTalkTenants,
  useExternalIdentities,
  useIdentityProviders,
  useSelfOnesBinding,
  useUnbindAdminOnesCredential,
  useUnbindIdentity,
  useUnbindSelfOnesBinding,
  useUpdateIdentityStatus,
} from "@/contexts/external-identities/application/external-identity-queries"
import type {
  DingTalkTenant,
  ExternalIdentity,
  OnesBindingChallenge,
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

type ExternalIdentityPanelProps =
  | {
      mode: "self"
      user?: never
      discoveryCandidateId?: never
    }
  | {
      mode?: "admin"
      user: User
      discoveryCandidateId?: string
    }

export function ExternalIdentityPanel(props: ExternalIdentityPanelProps) {
  if (props.mode === "self") return <SelfExternalIdentityPanel />
  return (
    <AdminExternalIdentityPanel
      user={props.user}
      discoveryCandidateId={props.discoveryCandidateId}
    />
  )
}

function AdminExternalIdentityPanel({
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
  const [binding, setBinding] = useState<"dingtalk" | null>(null)
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
              disabled
              title="ONES 凭据只能由用户本人验证"
            >
              <KeyRoundIcon aria-hidden="true" />
              ONES 由本人绑定
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
      {!onesProvider?.available ? (
        <p className="sr-only">ONES Provider 当前不可用</p>
      ) : null}
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
  const credential = useAdminOnesCredential(
    identity.provider === "ones" ? userId : "",
  )
  const disableCredential = useDisableAdminOnesCredential(userId)
  const unbindCredential = useUnbindAdminOnesCredential(userId)
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
        {identity.provider === "ones" ? (
          <IdentityField
            label="个人凭据"
            value={credential.data?.credential?.status ?? "credential missing"}
          />
        ) : null}
        {identity.provider === "ones" &&
        credential.data?.credential?.last_error_code ? (
          <IdentityField
            label="最近错误"
            value={credential.data.credential.last_error_code}
          />
        ) : null}
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
      <RequestError
        error={
          updateStatus.error ||
          unbind.error ||
          credential.error ||
          disableCredential.error ||
          unbindCredential.error
        }
      />
      <div className="mt-4 flex flex-wrap gap-2">
        {identity.provider === "dingtalk" ? (
          <>
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
          </>
        ) : null}
        {identity.provider === "ones" &&
        credential.data?.credential?.status === "ACTIVE" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={disableCredential.isPending}
            onClick={() => disableCredential.mutate()}
          >
            停用个人凭据
          </Button>
        ) : null}
        {identity.provider === "ones" && identity.status !== "unbound" ? (
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={unbindCredential.isPending}
            onClick={() => setConfirmUnbind(true)}
          >
            <UnlinkIcon aria-hidden="true" />
            软解绑 ONES
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
        onConfirm={
          identity.provider === "ones"
            ? () =>
                unbindCredential.mutate(undefined, {
                  onSuccess: () => setConfirmUnbind(false),
                })
            : remove
        }
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

function SelfExternalIdentityPanel() {
  const status = useSelfOnesBinding()
  const unbind = useUnbindSelfOnesBinding()
  const [binding, setBinding] = useState(false)
  const [confirmUnbind, setConfirmUnbind] = useState(false)
  const identity = status.data?.identity
  const credential = status.data?.credential
  const credentialLabel = credential
    ? {
        ACTIVE: "凭据有效",
        INVALID: "凭据无效，请重新验证",
        DISABLED: "凭据已被管理员停用，请重新验证",
        UNBOUND: "已解绑",
      }[credential.status]
    : identity
      ? "credential missing，请重新验证"
      : "尚未绑定"

  return (
    <Card className="shadow-none">
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>ONES 本人身份</CardTitle>
            <CardDescription className="mt-1">
              登录验证后保存 ONES User ID、Team 候选、默认 Team
              与加密 Token；密码不会保存。
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={status.isLoading || status.isError}
            onClick={() => setBinding(true)}
          >
            <KeyRoundIcon />
            {identity ? "重新验证 / 切换默认 Team" : "绑定 ONES"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {status.isLoading ? (
          <div className="flex min-h-28 items-center justify-center gap-2 text-sm text-muted-foreground">
            <LoaderCircleIcon className="animate-spin" />
            正在加载本人 ONES 状态…
          </div>
        ) : null}
        <RequestError error={status.error || unbind.error} />
        <article className="rounded-xl border bg-muted/20 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold">
              {identity?.display_name || status.data?.user?.display_name || "ONES"}
            </h3>
            <Badge variant={credential?.status === "ACTIVE" ? "secondary" : "outline"}>
              {credentialLabel}
            </Badge>
          </div>
          {identity ? (
            <>
              <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
                <IdentityField
                  label="ONES User ID"
                  value={identity.external_subject_id}
                  mono
                />
                <IdentityField
                  label="默认 Team"
                  value={identity.metadata.default_team_id || "未选择"}
                  mono
                />
                <IdentityField
                  label="凭据 Revision"
                  value={credential ? `r${credential.revision}` : "missing"}
                />
                <IdentityField
                  label="最近验证"
                  value={formatDate(credential?.verified_at)}
                />
              </dl>
              <div className="mt-3 flex flex-wrap gap-1">
                {(identity.metadata.team_uuids ?? []).map((team) => (
                  <Badge
                    key={team}
                    variant={
                      team === identity.metadata.default_team_id
                        ? "secondary"
                        : "outline"
                    }
                    className="font-mono font-normal"
                  >
                    {team}
                  </Badge>
                ))}
              </div>
              {identity.status !== "unbound" ? (
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  className="mt-4"
                  onClick={() => setConfirmUnbind(true)}
                >
                  <UnlinkIcon />
                  解绑 ONES
                </Button>
              ) : null}
            </>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              尚未绑定 ONES。钉钉身份由消息入口或管理员人员详情治理，本页面不会请求其他用户资料。
            </p>
          )}
        </article>
      </CardContent>
      <SelfOnesBindingSheet
        open={binding}
        onOpenChange={setBinding}
        hasExisting={Boolean(identity)}
      />
      <ConfirmationSheet
        open={confirmUnbind}
        onOpenChange={setConfirmUnbind}
        title="解绑本人 ONES"
        description="解绑会软停用当前 ONES 身份和个人凭据并保留审计历史。"
        confirmLabel="确认解绑"
        destructive
        pending={unbind.isPending}
        onConfirm={() =>
          unbind.mutate(undefined, {
            onSuccess: () => setConfirmUnbind(false),
          })
        }
      />
    </Card>
  )
}

function SelfOnesBindingSheet({
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
      const next = await begin.mutateAsync({
        email: email.trim(),
        password,
      })
      setChallenge(next)
      setTeamId(next.teams[0]?.id ?? "")
    } catch {
      // The mutation error is rendered in the sheet.
    } finally {
      setPassword("")
    }
  }
  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!challenge) return
    try {
      await confirm.mutateAsync({
        challenge_id: challenge.id,
        connection_revision_id: challenge.connection_revision_id,
        default_team_id: teamId,
        replace_existing: replaceExisting,
      })
      toast.success("ONES 身份与默认 Team 已保存")
      changeOpen(false)
    } catch {
      // The mutation error is rendered in the sheet.
    }
  }

  return (
    <Sheet open={open} onOpenChange={changeOpen}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>本人验证 ONES 身份</SheetTitle>
          <SheetDescription>
            第一步验证邮箱密码并读取最新 Team；第二步选择默认 Team 后原子保存身份与加密凭据。
          </SheetDescription>
        </SheetHeader>
        {!challenge ? (
        <form className="space-y-4 px-4" onSubmit={verify}>
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
          <RequestError error={begin.error} />
          <SheetFooter className="px-0">
            <Button type="submit" disabled={begin.isPending}>
              {begin.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : null}
              验证并读取 Team
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
        ) : (
          <form className="space-y-4 px-4" onSubmit={save}>
            <div className="rounded-lg border bg-muted/20 p-4 text-sm">
              <p className="font-medium">{challenge.display_name}</p>
              <p className="mt-1 font-mono text-xs text-muted-foreground">
                {challenge.external_user_id}
              </p>
            </div>
            <Field
              label="默认 Team"
              htmlFor="ones-default-team"
              hint="Agent 调用时从用户绑定快照注入，不能由 Agent 参数覆盖。"
            >
              <select
                id="ones-default-team"
                required
                className="h-8 w-full rounded-lg border border-input bg-background px-2.5 text-sm"
                value={teamId}
                onChange={(event) => setTeamId(event.target.value)}
              >
                {challenge.teams.map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.name || team.id} · {team.id}
                  </option>
                ))}
              </select>
            </Field>
            {hasExisting ? (
              <label className="flex items-start gap-2 rounded-lg border p-3 text-sm">
                <Checkbox
                  checked={replaceExisting}
                  onCheckedChange={(checked) =>
                    setReplaceExisting(Boolean(checked))
                  }
                />
                <span>
                  如果验证结果是另一个 ONES User ID，确认换绑当前账号
                </span>
              </label>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Challenge 将于 {formatDate(challenge.expires_at)} 失效，且只能消费一次。
            </p>
            <RequestError error={confirm.error} />
            <SheetFooter className="px-0">
              <Button type="submit" disabled={confirm.isPending || !teamId}>
                {confirm.isPending ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : null}
                保存身份与默认 Team
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => setChallenge(null)}
              >
                返回重新验证
              </Button>
            </SheetFooter>
          </form>
        )}
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
