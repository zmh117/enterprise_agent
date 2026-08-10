import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCwIcon, SearchIcon, UserRoundCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  bindIdentityCandidate,
  listIdentityCandidates,
  type DingTalkIdentityCandidate,
} from "@/contexts/dingtalk-identity-discovery/infrastructure/identity-candidate-api"
import {
  listRoles,
  listUsers,
} from "@/contexts/identity-governance/infrastructure/identity-governance-api"
import {
  ManagementError,
  ManagementLoading,
  ManagementPage,
  MutationNotice,
} from "@/shared/presentation/management-states"
import { SectionHeading } from "@/shared/presentation/section-heading"

const candidateKey = ["admin", "identity-candidates"] as const

export function IdentityDiscoveryPage() {
  const [draftSearch, setDraftSearch] = useState("")
  const [search, setSearch] = useState("")
  const [scope, setScope] = useState("all")
  const [binding, setBinding] = useState<DingTalkIdentityCandidate | null>(null)
  const query = useQuery({
    queryKey: [...candidateKey, search, scope],
    queryFn: () => listIdentityCandidates({ search, conversationScope: scope }),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setSearch(draftSearch.trim())
  }
  return <ManagementPage>
    <SectionHeading eyebrow="Identity Governance" title="未绑定钉钉用户" description="只展示最近 30 天由受信钉钉连接器观察到、尚未绑定的用户；绑定后关联到统一 app_user，不创建第二套人员事实。" action={<Button type="button" variant="outline" onClick={() => void query.refetch()}><RefreshCwIcon className={query.isFetching ? "animate-spin" : ""} />刷新</Button>} />
    <Card className="shadow-none"><CardContent className="p-4"><form className="flex flex-col gap-2 sm:flex-row" onSubmit={submit}><div className="relative flex-1"><SearchIcon className="pointer-events-none absolute top-2.5 left-3 size-4 text-muted-foreground" /><Input className="pl-9" value={draftSearch} onChange={(event) => setDraftSearch(event.target.value)} placeholder="钉钉名称、Subject、群或机器人" aria-label="搜索待绑定钉钉用户" /></div><select value={scope} onChange={(event) => setScope(event.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm" aria-label="会话范围"><option value="all">全部</option><option value="direct">私聊</option><option value="group">群聊</option><option value="both">私聊与群聊</option></select><Button type="submit" variant="outline">搜索</Button></form></CardContent></Card>
    {binding ? <CandidateBinding candidate={binding} onCancel={() => setBinding(null)} onDone={() => { setBinding(null); void query.refetch() }} /> : null}
    {query.isLoading ? <ManagementLoading /> : null}<ManagementError error={query.error} retry={() => void query.refetch()} />
    <div className="space-y-3">{query.data?.candidates.map((candidate) => <Card key={candidate.id} className="shadow-none"><CardContent className="flex flex-wrap items-start justify-between gap-4 p-4"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="font-medium">{candidate.display_name || "未提供钉钉名称"}</p><Badge variant="outline">{candidate.conversation_scope === "direct" ? "私聊" : candidate.conversation_scope === "group" ? "群聊" : "私聊 + 群聊"}</Badge><Badge variant="secondary">{candidate.observation_count} 次观测</Badge>{candidate.identity_state === "restore_required" ? <Badge variant="outline">恢复历史身份</Badge> : null}</div><p className="mt-1 break-all font-mono text-xs text-muted-foreground">{candidate.external_subject_id}</p><p className="mt-1 text-xs text-muted-foreground">{candidate.enterprise_name} · {candidate.connector_names.join("、") || "连接器未知"} · 最近 {formatTime(candidate.last_seen_at)}</p>{candidate.latest_message ? <p className="mt-2 max-w-3xl whitespace-pre-wrap text-sm text-muted-foreground">{candidate.latest_message.safe_text || candidate.latest_message.attachment_name || `消息类型：${candidate.latest_message.message_kind}`}</p> : null}</div><Button type="button" variant="outline" onClick={() => setBinding(candidate)}><UserRoundCheckIcon />{candidate.identity_state === "restore_required" ? "恢复归属" : "绑定人员"}</Button></CardContent></Card>)}{query.data && !query.data.candidates.length ? <p className="py-10 text-center text-sm text-muted-foreground">当前没有待绑定钉钉用户。</p> : null}</div>
  </ManagementPage>
}

function CandidateBinding({ candidate, onCancel, onDone }: { candidate: DingTalkIdentityCandidate; onCancel: () => void; onDone: () => void }) {
  const users = useQuery({ queryKey: ["admin", "users", "identity-bind"], queryFn: () => listUsers("") })
  const roles = useQuery({ queryKey: ["admin", "roles", "identity-bind"], queryFn: () => listRoles("") })
  const client = useQueryClient()
  const fixedUserId = candidate.historical_identity?.user_id || ""
  const [targetUserId, setTargetUserId] = useState(fixedUserId)
  const [roleIds, setRoleIds] = useState<Set<string>>(new Set())
  const [bindOnly, setBindOnly] = useState(false)
  const target = users.data?.users.find((item) => item.id === targetUserId)
  const mutation = useMutation({ mutationFn: bindIdentityCandidate, onSuccess: async () => { await client.invalidateQueries({ queryKey: candidateKey }); onDone() } })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!target) return
    mutation.mutate({ candidateId: candidate.id, targetUserId: target.id, expectedCandidateRevision: candidate.revision, expectedUserRevision: target.revision, initialRoleIds: [...roleIds], bindWithoutAccessConfirmed: bindOnly })
  }
  return <Card className="border-primary/30 shadow-none"><CardHeader><CardTitle>{candidate.identity_state === "restore_required" ? "恢复历史钉钉身份" : "绑定到系统人员"}</CardTitle></CardHeader><CardContent><form className="grid gap-4 md:grid-cols-2" onSubmit={submit}><div className="space-y-2"><Label htmlFor="candidate-user">目标人员</Label><select id="candidate-user" className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={targetUserId} disabled={Boolean(fixedUserId)} onChange={(event) => setTargetUserId(event.target.value)} required><option value="">请选择已存在人员</option>{users.data?.users.filter((item) => item.status === "enabled" && item.account_type === "human").map((item) => <option key={item.id} value={item.id}>{item.display_name} (@{item.username})</option>)}</select>{fixedUserId ? <p className="text-xs text-muted-foreground">历史身份只能恢复到原人员，不能改绑给其他人。</p> : null}</div><div className="space-y-2"><Label>初始角色</Label><div className="max-h-40 space-y-2 overflow-y-auto rounded-md border p-3">{roles.data?.items.filter((role) => role.status === "enabled" && !role.protected).map((role) => <label key={role.id} className="flex items-center gap-2 text-sm"><Checkbox checked={roleIds.has(role.id)} disabled={bindOnly} onCheckedChange={(checked) => { const next = new Set(roleIds); if (checked) next.add(role.id); else next.delete(role.id); setRoleIds(next) }} />{role.name}</label>)}</div></div><label className="flex items-start gap-2 rounded-md border p-3 text-sm md:col-span-2"><Checkbox checked={bindOnly} disabled={roleIds.size > 0} onCheckedChange={(checked) => setBindOnly(Boolean(checked))} /><span>仅绑定身份，暂不授予 Application 或管理权限</span></label><div className="md:col-span-2"><ManagementError error={users.error || roles.error} retry={() => { void users.refetch(); void roles.refetch() }} /><MutationNotice error={mutation.error} /></div><div className="flex gap-2 md:col-span-2"><Button type="submit" disabled={!target || (!roleIds.size && !bindOnly) || mutation.isPending}>确认绑定</Button><Button type="button" variant="outline" onClick={onCancel}>取消</Button></div></form></CardContent></Card>
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN")
}
