import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import {
  KeyRoundIcon,
  Link2Icon,
  LoaderCircleIcon,
  UnlinkIcon,
} from "lucide-react"
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
import { Checkbox } from "@/components/ui/checkbox"
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
  useBeginSelfOnesIdentity,
  useConfirmSelfOnesIdentity,
  useExternalIdentities,
  useSelfExternalIdentities,
  useUnbindIdentity,
  useUnbindSelfOnesIdentity,
  useUpdateIdentityStatus,
} from "@/contexts/external-identities/application/external-identity-queries"
import type {
  AdminDingTalkIdentity,
  AdminExternalIdentity,
  AdminOnesIdentity,
  OnesIdentityChallenge,
  SelfDingTalkIdentity,
  SelfOnesIdentity,
} from "@/contexts/external-identities/domain/external-identity"
import {
  useBindDingTalkIdentityCandidate,
  useDingTalkIdentityCandidate,
} from "@/contexts/dingtalk-identity-discovery/application/dingtalk-identity-candidate-queries"
import { useRoles } from "@/contexts/authorization/application/role-authorization-queries"
import type { User } from "@/contexts/users/domain/user"
import { formatDate } from "@/contexts/users/presentation/format-date"
import {
  ConfirmationSheet,
  Field,
  RequestError,
} from "@/contexts/users/presentation/user-ui"

type ExternalIdentityPanelProps =
  | { mode: "self"; user?: never; discoveryCandidateId?: never }
  | { mode?: "admin"; user: User; discoveryCandidateId?: string }

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
  const navigate = useNavigate()
  const identities = useExternalIdentities(user.id)
  const candidate = useDingTalkIdentityCandidate(discoveryCandidateId)
  const [candidateDismissed, setCandidateDismissed] = useState(false)
  const current = identities.data?.current ?? []
  const history = identities.data?.history ?? []

  return (
    <Card className="shadow-none">
      <CardHeader className="border-b">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>外部身份治理</CardTitle>
            <CardDescription className="mt-1">
              钉钉身份来自已验证企业的受信消息；ONES 身份只能由用户本人验证。
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={
              user.account_type !== "human" || user.status !== "enabled"
            }
            onClick={() => navigate("/users/dingtalk-discovery")}
          >
            <Link2Icon aria-hidden="true" />
            从受信候选绑定钉钉
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {user.account_type !== "human" ? (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            服务账号不能绑定个人外部身份。
          </p>
        ) : null}
        {identities.isLoading ? (
          <Loading label="正在加载身份治理信息…" />
        ) : null}
        <RequestError error={identities.error || candidate.error} />
        {current.length === 0 && !identities.isLoading ? (
          <div className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
            该用户当前没有已绑定的钉钉或 ONES 身份。
          </div>
        ) : null}
        {current.length > 0 ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {current.map((identity) => (
              <AdminIdentityCard
                key={identity.identity_id}
                identity={identity}
                userId={user.id}
              />
            ))}
          </div>
        ) : null}
        {history.length > 0 ? (
          <details
            data-testid="external-identity-history"
            className="rounded-xl border bg-muted/10"
            open={candidate.data?.identity_state === "restore_required"}
          >
            <summary className="cursor-pointer px-4 py-3 font-medium">
              历史记录（{history.length}）
            </summary>
            <div className="grid gap-3 border-t p-4 lg:grid-cols-2">
              {history.map((identity) => (
                <HistoricalIdentityCard
                  key={identity.identity_id}
                  identity={identity}
                />
              ))}
            </div>
          </details>
        ) : null}
      </CardContent>
      <CandidateDingTalkBindingSheet
        open={Boolean(discoveryCandidateId) && !candidateDismissed}
        onOpenChange={(open) => {
          if (!open) setCandidateDismissed(true)
        }}
        user={user}
        candidateId={discoveryCandidateId}
        currentDingTalkCorpIds={current.flatMap((identity) =>
          identity.provider === "dingtalk" && identity.enterprise
            ? [identity.enterprise.corp_id]
            : []
        )}
      />
    </Card>
  )
}

function AdminIdentityCard({
  identity,
  userId,
}: {
  identity: AdminExternalIdentity
  userId: string
}) {
  return identity.provider === "dingtalk" ? (
    <AdminDingTalkCard identity={identity} userId={userId} />
  ) : (
    <AdminOnesCard identity={identity} userId={userId} />
  )
}

function AdminDingTalkCard({
  identity,
  userId,
}: {
  identity: AdminDingTalkIdentity
  userId: string
}) {
  const update = useUpdateIdentityStatus(userId)
  const unbind = useUnbindIdentity(userId)
  const [confirmUnbind, setConfirmUnbind] = useState(false)
  const nextStatus = identity.status === "enabled" ? "disabled" : "enabled"
  return (
    <article className="rounded-xl border bg-muted/20 p-4">
      <IdentityHeading
        title="钉钉身份"
        name={identity.nickname || "钉钉未返回昵称"}
        badge={identity.status === "enabled" ? "已启用" : "已停用"}
        active={identity.status === "enabled"}
      />
      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
        <IdentityField
          label="钉钉企业"
          value={identity.enterprise?.name || "历史企业信息不可用"}
        />
        <IdentityField
          label="最近使用"
          value={formatDate(identity.last_used_at)}
        />
      </dl>
      <details className="mt-4 rounded-lg border bg-background px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium">
          技术详情
        </summary>
        <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
          <IdentityField label="Staff ID" value={identity.staff_id} mono />
          <IdentityField
            label="Corp ID"
            value={identity.enterprise?.corp_id || "历史企业信息不可用"}
            mono
          />
          <IdentityField
            label="绑定确认时间"
            value={formatDate(identity.binding_confirmed_at)}
          />
          <IdentityField
            label="身份 Revision"
            value={`r${identity.revision}`}
          />
        </dl>
        <div className="mt-3 space-y-2">
          <p className="text-xs font-medium">应用观察</p>
          {identity.observations.length ? (
            identity.observations.map((item) => (
              <div
                key={item.application_name}
                className="rounded-md bg-muted/40 p-2 text-xs"
              >
                <div className="font-medium">{item.application_name}</div>
                <div className="mt-1 text-muted-foreground">
                  首次 {formatDate(item.first_observed_at)} · 最近{" "}
                  {formatDate(item.last_observed_at)}
                </div>
              </div>
            ))
          ) : (
            <p className="text-xs text-muted-foreground">尚无应用观察记录</p>
          )}
        </div>
      </details>
      <RequestError error={update.error || unbind.error} />
      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={update.isPending}
          onClick={() =>
            update.mutate({
              identityId: identity.identity_id,
              expectedRevision: identity.revision,
              status: nextStatus,
            })
          }
        >
          {identity.status === "enabled" ? "停用身份" : "启用身份"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="destructive"
          onClick={() => setConfirmUnbind(true)}
        >
          <UnlinkIcon aria-hidden="true" />
          解绑
        </Button>
      </div>
      <ConfirmationSheet
        open={confirmUnbind}
        onOpenChange={setConfirmUnbind}
        title="解绑钉钉身份"
        description="解绑会同时停止该企业下全部钉钉应用解析此身份，并保留审计历史。"
        confirmLabel="确认解绑"
        destructive
        pending={unbind.isPending}
        onConfirm={() =>
          unbind.mutate(
            {
              identityId: identity.identity_id,
              expectedRevision: identity.revision,
            },
            { onSuccess: () => setConfirmUnbind(false) }
          )
        }
      />
    </article>
  )
}

function AdminOnesCard({
  identity,
  userId,
}: {
  identity: AdminOnesIdentity
  userId: string
}) {
  const update = useUpdateIdentityStatus(userId)
  return (
    <article className="rounded-xl border bg-muted/20 p-4">
      <IdentityHeading
        title="ONES 身份"
        name={identity.user_name}
        badge={identityStatusLabel(identity.status)}
        active={identity.status === "enabled"}
      />
      <OnesBusinessSummary identity={identity} />
      <details className="mt-4 rounded-lg border bg-background px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium">
          管理员技术详情
        </summary>
        <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
          <IdentityField label="ONES User ID" value={identity.user_id} mono />
          <IdentityField
            label="身份记录"
            value={`${identity.identity_id} · r${identity.revision}`}
            mono
          />
          <IdentityField
            label="身份绑定状态"
            value={identityStatusLabel(identity.status)}
          />
        </dl>
        <TeamList
          teams={identity.teams}
          defaultTeamId={identity.default_team?.id}
        />
      </details>
      <RequestError error={update.error} />
      <div className="mt-4 flex flex-wrap gap-2">
        {identity.status === "enabled" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() =>
              update.mutate({
                identityId: identity.identity_id,
                expectedRevision: identity.revision,
                status: "disabled",
              })
            }
          >
            停用身份
          </Button>
        ) : null}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        管理员只能查看、停用和审计；重新验证与解绑必须由用户本人完成。
      </p>
    </article>
  )
}

function HistoricalIdentityCard({
  identity,
}: {
  identity: AdminExternalIdentity
}) {
  return (
    <article className="rounded-xl border bg-background p-4">
      <IdentityHeading
        title={
          identity.provider === "dingtalk" ? "历史钉钉身份" : "历史 ONES 身份"
        }
        name={
          identity.provider === "dingtalk"
            ? identity.nickname || "钉钉未返回昵称"
            : identity.user_name
        }
        badge="已解绑"
        active={false}
      />
      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
        {identity.provider === "dingtalk" ? (
          <>
            <IdentityField
              label="钉钉企业"
              value={identity.enterprise?.name || "历史企业信息不可用"}
            />
            <IdentityField label="Staff ID" value={identity.staff_id} mono />
          </>
        ) : (
          <>
            <IdentityField label="ONES User ID" value={identity.user_id} mono />
            <IdentityField
              label="最近验证"
              value={formatDate(identity.verified_at)}
            />
          </>
        )}
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">
        历史身份只读；钉钉身份只能通过匹配的受信候选恢复到原人员。
      </p>
    </article>
  )
}

function SelfExternalIdentityPanel() {
  const overview = useSelfExternalIdentities()
  const unbind = useUnbindSelfOnesIdentity()
  const [binding, setBinding] = useState(false)
  const [confirmUnbind, setConfirmUnbind] = useState(false)
  const ones = overview.data?.ones ?? null
  return (
    <Card className="shadow-none">
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>我的外部身份</CardTitle>
            <CardDescription className="mt-1">
              钉钉身份只读；ONES 登录材料确认后加密保存，仅供本人查询与 Token 刷新。
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={overview.isLoading || overview.isError}
            onClick={() => setBinding(true)}
          >
            <KeyRoundIcon aria-hidden="true" />
            {ones ? "重新验证 / 切换默认 Team" : "绑定 ONES"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {overview.isLoading ? <Loading label="正在加载我的外部身份…" /> : null}
        <RequestError error={overview.error || unbind.error} />
        {overview.data?.dingtalk.map((identity) => (
          <SelfDingTalkCard
            key={`${identity.enterprise?.corp_id}:${identity.staff_id}`}
            identity={identity}
          />
        ))}
        <article className="rounded-xl border bg-muted/20 p-4">
          <IdentityHeading
            title="ONES 本人身份"
            name={ones?.user_name || "尚未绑定 ONES"}
            badge={ones ? identityStatusLabel(ones.status) : "尚未绑定"}
            active={ones?.status === "enabled"}
          />
          {ones ? (
            <>
              <OnesBusinessSummary identity={ones} />
              <details className="mt-4 rounded-lg border bg-background px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium">
                  我的 ONES 账户详情
                </summary>
                <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
                  <IdentityField
                    label="ONES User ID"
                    value={ones.user_id}
                    mono
                  />
                </dl>
                <TeamList
                  teams={ones.teams}
                  defaultTeamId={ones.default_team?.id}
                />
              </details>
              <Button
                type="button"
                size="sm"
                variant="destructive"
                className="mt-4"
                onClick={() => setConfirmUnbind(true)}
              >
                <UnlinkIcon aria-hidden="true" />
                解绑 ONES
              </Button>
            </>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              完成本人验证并选择默认 Team 后，平台会保存身份映射与加密凭据；实际查询仍需 Agent、应用和角色共同授权。
            </p>
          )}
        </article>
      </CardContent>
      <SelfOnesBindingSheet
        open={binding}
        onOpenChange={setBinding}
        hasExisting={Boolean(ones)}
      />
      <ConfirmationSheet
        open={confirmUnbind}
        onOpenChange={setConfirmUnbind}
        title="解绑本人 ONES"
        description="解绑会软停用当前 ONES 身份、立即清除加密登录材料与 Token，并保留审计历史。"
        confirmLabel="确认解绑"
        destructive
        pending={unbind.isPending}
        onConfirm={() =>
          unbind.mutate(undefined, { onSuccess: () => setConfirmUnbind(false) })
        }
      />
    </Card>
  )
}

function SelfDingTalkCard({ identity }: { identity: SelfDingTalkIdentity }) {
  return (
    <article className="rounded-xl border bg-muted/20 p-4">
      <IdentityHeading
        title="钉钉身份"
        name={identity.nickname || "钉钉未返回昵称"}
        badge={`${identity.status === "enabled" ? "已启用" : "已停用"} · 只读`}
        active={identity.status === "enabled"}
      />
      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
        <IdentityField
          label="钉钉企业"
          value={identity.enterprise?.name || "企业信息不可用"}
        />
        <IdentityField
          label="最近使用"
          value={formatDate(identity.last_used_at)}
        />
      </dl>
      <details className="mt-4 rounded-lg border bg-background px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium">
          身份详情
        </summary>
        <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
          <IdentityField label="Staff ID" value={identity.staff_id} mono />
          <IdentityField
            label="Corp ID"
            value={identity.enterprise?.corp_id || "企业信息不可用"}
            mono
          />
        </dl>
      </details>
    </article>
  )
}

function OnesBusinessSummary({
  identity,
}: {
  identity: Pick<
    SelfOnesIdentity,
    "default_team" | "verified_at" | "credential"
  >
}) {
  return (
    <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
      <IdentityField
        label="默认 Team"
        value={formatTeam(identity.default_team)}
      />
      <IdentityField
        label="最近验证"
        value={formatDate(identity.verified_at)}
      />
      <IdentityField
        label="查询凭据"
        value={credentialStatusLabel(identity.credential)}
      />
      <IdentityField
        label="最近使用 / Token 刷新"
        value={
          identity.credential
            ? `${formatDate(identity.credential.last_used_at)} / ${formatDate(
                identity.credential.token_refreshed_at
              )}`
            : "需要本人重新验证"
        }
      />
    </dl>
  )
}

function TeamList({
  teams,
  defaultTeamId,
}: {
  teams: Array<{ id: string; name: string }>
  defaultTeamId?: string
}) {
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs font-medium">
        可用 Team（{teams.length}）
      </summary>
      <div className="mt-2 flex flex-wrap gap-1">
        {teams.map((team) => (
          <Badge
            key={team.id}
            variant={team.id === defaultTeamId ? "secondary" : "outline"}
            className="font-normal"
          >
            {formatTeam(team)}
          </Badge>
        ))}
      </div>
    </details>
  )
}

function CandidateDingTalkBindingSheet({
  open,
  onOpenChange,
  user,
  candidateId,
  currentDingTalkCorpIds,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User
  candidateId: string
  currentDingTalkCorpIds: string[]
}) {
  const navigate = useNavigate()
  const candidate = useDingTalkIdentityCandidate(candidateId)
  const mutation = useBindDingTalkIdentityCandidate(candidateId, user.id)
  const roles = useRoles({ search: "", status: "enabled", origin: "" })
  const [initialRoleIds, setInitialRoleIds] = useState<Set<string>>(new Set())
  const [bindOnly, setBindOnly] = useState(false)
  const [replaceCurrent, setReplaceCurrent] = useState(false)
  const requiresReplacement = Boolean(
    candidate.data &&
    currentDingTalkCorpIds.includes(candidate.data.corp_id) &&
    !(
      candidate.data.historical_identity?.user_id === user.id &&
      candidate.data.historical_identity.status === "disabled"
    )
  )
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
        replace_current_confirmed: replaceCurrent,
      },
      {
        onSuccess: () => {
          toast.success(
            candidate.data?.identity_state === "restore_required"
              ? "钉钉身份已恢复"
              : "钉钉用户已绑定"
          )
          navigate("/users/dingtalk-discovery")
        },
      }
    )
  }
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>确认受信钉钉候选</SheetTitle>
          <SheetDescription>
            企业、Staff ID、昵称和来源应用均由服务端候选重读，不能手工输入。
          </SheetDescription>
        </SheetHeader>
        {candidate.isLoading ? <Loading label="正在加载候选信息…" /> : null}
        {candidate.data ? (
          <form className="space-y-4 px-4" onSubmit={submit}>
            <dl className="grid gap-3 rounded-lg border bg-muted/20 p-4 text-xs sm:grid-cols-2">
              <IdentityField
                label="钉钉企业"
                value={candidate.data.enterprise_name}
              />
              <IdentityField
                label="Corp ID"
                value={candidate.data.corp_id}
                mono
              />
              <IdentityField
                label="Staff ID"
                value={candidate.data.external_subject_id}
                mono
              />
              <IdentityField
                label="钉钉昵称"
                value={candidate.data.display_name || "钉钉未返回昵称"}
              />
              <IdentityField
                label="来源应用"
                value={
                  candidate.data.latest_message?.connector_name ||
                  "来源应用不可用"
                }
              />
              <IdentityField
                label="目标人员"
                value={`${user.display_name}（${user.username}）`}
              />
            </dl>
            <div className="space-y-3 rounded-lg border p-4">
              <p className="text-sm font-medium">初始角色</p>
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
                  {role.name}
                </label>
              ))}
              <label className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-sm">
                <Checkbox
                  checked={bindOnly}
                  disabled={initialRoleIds.size > 0}
                  onCheckedChange={(checked) => setBindOnly(Boolean(checked))}
                />
                <span>仅绑定身份，暂不授权</span>
              </label>
              {requiresReplacement ? (
                <label className="flex items-start gap-2 rounded-md bg-red-50 p-3 text-sm">
                  <Checkbox
                    checked={replaceCurrent}
                    onCheckedChange={(checked) =>
                      setReplaceCurrent(Boolean(checked))
                    }
                  />
                  <span>
                    确认替换该企业下现有钉钉身份；旧身份将软解绑并影响该企业的全部应用。
                  </span>
                </label>
              ) : null}
            </div>
            <RequestError error={roles.error || mutation.error} />
            <SheetFooter className="px-0">
              <Button
                type="submit"
                disabled={
                  mutation.isPending ||
                  (initialRoleIds.size === 0 && !bindOnly) ||
                  (requiresReplacement && !replaceCurrent)
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
                onClick={() => onOpenChange(false)}
              >
                取消
              </Button>
            </SheetFooter>
          </form>
        ) : null}
        <RequestError error={candidate.error} />
      </SheetContent>
    </Sheet>
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
  const begin = useBeginSelfOnesIdentity()
  const confirm = useConfirmSelfOnesIdentity()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [challenge, setChallenge] = useState<OnesIdentityChallenge | null>(null)
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
      // The mutation exposes the safe server error in the sheet.
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
    toast.success("ONES 身份与默认 Team 已保存")
    changeOpen(false)
  }
  return (
    <Sheet open={open} onOpenChange={changeOpen}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{hasExisting ? "重新验证 ONES" : "绑定 ONES"}</SheetTitle>
          <SheetDescription>
            邮箱和密码只在当前页面内存中输入；确认后平台会加密保存登录材料与当前 Token，用于本人授权查询和 Token 自动刷新，公开页面不会返回原文。
          </SheetDescription>
        </SheetHeader>
        {!challenge ? (
          <form className="space-y-4 px-4" onSubmit={verify}>
            <Field label="ONES 邮箱" htmlFor="ones-email">
              <Input
                id="ones-email"
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </Field>
            <Field label="一次性验证密码" htmlFor="ones-password">
              <Input
                id="ones-password"
                type="password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </Field>
            <RequestError error={begin.error} />
            <SheetFooter className="px-0">
              <Button type="submit" disabled={begin.isPending}>
                {begin.isPending ? (
                  <LoaderCircleIcon
                    className="animate-spin"
                    aria-hidden="true"
                  />
                ) : null}
                验证并读取 Team
              </Button>
            </SheetFooter>
          </form>
        ) : (
          <form className="space-y-4 px-4" onSubmit={save}>
            <div className="rounded-lg border bg-muted/20 p-4 text-sm">
              <div className="font-medium">
                {challenge.display_name || "ONES 未返回用户名称"}
              </div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">
                {challenge.external_user_id}
              </div>
            </div>
            <Field label="默认 Team" htmlFor="ones-team">
              <select
                id="ones-team"
                required
                className="h-9 w-full rounded-lg border bg-background px-3 text-sm"
                value={teamId}
                onChange={(event) => setTeamId(event.target.value)}
              >
                {challenge.teams.map((team) => (
                  <option key={team.id} value={team.id}>
                    {formatTeam(team)}
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
                <span>若登录的是其他 ONES 账号，确认替换当前绑定。</span>
              </label>
            ) : null}
            <RequestError error={confirm.error} />
            <SheetFooter className="px-0">
              <Button type="submit" disabled={confirm.isPending || !teamId}>
                {confirm.isPending ? (
                  <LoaderCircleIcon
                    className="animate-spin"
                    aria-hidden="true"
                  />
                ) : null}
                保存绑定
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => setChallenge(null)}
              >
                返回重试
              </Button>
            </SheetFooter>
          </form>
        )}
      </SheetContent>
    </Sheet>
  )
}

function IdentityHeading({
  title,
  name,
  badge,
  active,
}: {
  title: string
  name: string
  badge: string
  active: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        <h3 className="font-semibold">{title}</h3>
        <p className="mt-1 text-sm">{name}</p>
      </div>
      <Badge variant={active ? "secondary" : "outline"}>{badge}</Badge>
    </div>
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
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={`mt-1 break-all ${mono ? "font-mono" : ""}`}>
        {value || "—"}
      </dd>
    </div>
  )
}

function Loading({ label }: { label: string }) {
  return (
    <div className="flex min-h-24 items-center justify-center gap-2 text-sm text-muted-foreground">
      <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
      {label}
    </div>
  )
}

function formatTeam(team: { id: string; name: string } | null) {
  if (!team) return "未选择"
  return team.name ? `${team.name}（${team.id}）` : `${team.id}（名称暂不可用）`
}

function credentialStatusLabel(value: SelfOnesIdentity["credential"]) {
  if (!value || !value.configured) return "需要本人重新验证"
  return {
    ACTIVE: `可用 · r${value.revision}`,
    REAUTH_REQUIRED: `需要本人重新验证 · r${value.revision}`,
    DISABLED: `已停用 · r${value.revision}`,
    UNBOUND: `已解绑 · r${value.revision}`,
  }[value.status]
}

function identityStatusLabel(value: AdminOnesIdentity["status"]) {
  return { enabled: "已启用", disabled: "已停用", unbound: "已解绑" }[value]
}
