import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeftIcon,
  PlusIcon,
  RefreshCwIcon,
  SaveIcon,
  ShieldIcon,
  UserRoundIcon,
} from "lucide-react"
import { Link, useNavigate, useParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useAuthenticatedUser } from "@/contexts/auth/presentation/authenticated-user-state"
import {
  createRole,
  createUser,
  getRole,
  getUser,
  listAdminCapabilities,
  listAssignableApplications,
  listRoles,
  listUsers,
  revokeUserSession,
  updateRoleApplications,
  updateRoleCapabilities,
  updateRoleMember,
  updateRoleMetadata,
  updateUser,
  type AdminUser,
  type RoleDetail,
  type UserDetail,
} from "@/contexts/identity-governance/infrastructure/identity-governance-api"
import {
  ManagementError,
  ManagementLoading,
  ManagementPage,
  MutationNotice,
} from "@/shared/presentation/management-states"
import { SectionHeading } from "@/shared/presentation/section-heading"

const userKeys = {
  all: ["admin", "users"] as const,
  detail: (id: string) => ["admin", "users", id] as const,
}
const roleKeys = {
  all: ["admin", "roles"] as const,
  detail: (id: string) => ["admin", "roles", id] as const,
  capabilities: ["admin", "roles", "capabilities"] as const,
  applications: ["admin", "roles", "applications"] as const,
}

export function UsersPage() {
  const user = useAuthenticatedUser()
  const [search, setSearch] = useState("")
  const [creating, setCreating] = useState(false)
  const query = useQuery({
    queryKey: [...userKeys.all, search],
    queryFn: () => listUsers(search),
  })
  return (
    <ManagementPage>
      <SectionHeading
        eyebrow="Identity Governance"
        title="人员与账号"
        description="统一管理系统用户、角色成员、登录会话和外部身份；不会建立第二套人员或授权事实。"
        action={
          <div className="flex gap-2">
            <Button type="button" variant="outline" disabled={query.isFetching} onClick={() => void query.refetch()}>
              <RefreshCwIcon className={query.isFetching ? "animate-spin" : ""} />刷新
            </Button>
            {user.capabilities.users_manage ? (
              <Button type="button" onClick={() => setCreating((value) => !value)}><PlusIcon />新建用户</Button>
            ) : null}
          </div>
        }
      />
      <div className="max-w-md space-y-2">
        <Label htmlFor="user-search">搜索用户</Label>
        <Input id="user-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="用户名、显示名称或邮箱" />
      </div>
      {creating ? <CreateUserForm onDone={() => { setCreating(false); void query.refetch() }} /> : null}
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error} retry={() => void query.refetch()} />
      <div className="space-y-3">
        {query.data?.users.map((item) => (
          <Card key={item.id} className="shadow-none">
            <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <UserRoundIcon className="size-4" />
                  <p className="font-medium">{item.display_name}</p>
                  <Badge variant={item.status === "enabled" ? "secondary" : "outline"}>{item.status === "enabled" ? "启用" : "停用"}</Badge>
                  <Badge variant="outline">{item.account_type === "human" ? "人员" : "服务账号"}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">@{item.username}{item.email ? ` · ${item.email}` : ""} · r{item.revision}</p>
              </div>
              <Link to={`/users/${encodeURIComponent(item.id)}`} className={buttonVariants({ variant: "outline" })}>查看与治理</Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </ManagementPage>
  )
}

function CreateUserForm({ onDone }: { onDone: () => void }) {
  const mutation = useMutation({ mutationFn: createUser, onSuccess: onDone })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const password = String(data.get("password") || "")
    mutation.mutate({
      username: String(data.get("username") || ""),
      display_name: String(data.get("display_name") || ""),
      email: String(data.get("email") || ""),
      ...(password ? { password } : {}),
    })
  }
  return (
    <Card className="shadow-none"><CardHeader><CardTitle>新建人员账号</CardTitle></CardHeader><CardContent>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
        <Field name="username" label="用户名" required />
        <Field name="display_name" label="显示名称" required />
        <Field name="email" label="邮箱" type="email" />
        <Field name="password" label="初始密码（可选，至少 12 位）" type="password" />
        <div className="sm:col-span-2"><MutationNotice error={mutation.error} /></div>
        <Button type="submit" disabled={mutation.isPending}>创建账号</Button>
      </form>
    </CardContent></Card>
  )
}

export function UserDetailPage() {
  const id = useParams().userId ?? ""
  const query = useQuery({ queryKey: userKeys.detail(id), queryFn: () => getUser(id), enabled: Boolean(id) })
  if (query.isLoading) return <ManagementPage><ManagementLoading /></ManagementPage>
  if (!query.data) return <ManagementPage><Back href="/users" /><ManagementError error={query.error} retry={() => void query.refetch()} /></ManagementPage>
  return <UserEditor key={query.data.user.revision} detail={query.data} refresh={() => void query.refetch()} />
}

function UserEditor({ detail, refresh }: { detail: UserDetail; refresh: () => void }) {
  const current = useAuthenticatedUser()
  const client = useQueryClient()
  const [metadata, setMetadata] = useState({
    display_name: detail.user.display_name,
    email: detail.user.email,
    status: detail.user.status,
  })
  const update = useMutation({
    mutationFn: () => updateUser(detail.user.id, { expected_revision: detail.user.revision, ...metadata }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: userKeys.detail(detail.user.id) }) },
  })
  const revoke = useMutation({
    mutationFn: (sessionId: string) => revokeUserSession(detail.user.id, sessionId),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: userKeys.detail(detail.user.id) }) },
  })
  return (
    <ManagementPage>
      <Back href="/users" />
      <SectionHeading eyebrow="Identity Governance" title={detail.user.display_name} description={`@${detail.user.username} · ${detail.user.account_type === "human" ? "人员账号" : "服务账号"} · r${detail.user.revision}`} action={<Button type="button" variant="outline" onClick={refresh}><RefreshCwIcon />刷新</Button>} />
      <MutationNotice error={update.error || revoke.error} />
      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="shadow-none"><CardHeader><CardTitle>账号状态</CardTitle></CardHeader><CardContent className="grid gap-4">
          <FieldValue label="显示名称" value={metadata.display_name} disabled={!current.capabilities.users_manage} onChange={(value) => setMetadata({ ...metadata, display_name: value })} />
          <FieldValue label="邮箱" value={metadata.email} disabled={!current.capabilities.users_manage} onChange={(value) => setMetadata({ ...metadata, email: value })} />
          <div className="space-y-2"><Label htmlFor="user-status">状态</Label><select id="user-status" className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={metadata.status} disabled={!current.capabilities.users_manage} onChange={(event) => setMetadata({ ...metadata, status: event.target.value as "enabled" | "disabled" })}><option value="enabled">启用</option><option value="disabled">停用</option></select></div>
          {current.capabilities.users_manage ? <Button type="button" disabled={update.isPending} onClick={() => update.mutate()}><SaveIcon />保存账号</Button> : null}
        </CardContent></Card>
        <Card className="shadow-none"><CardHeader><CardTitle>角色成员关系</CardTitle></CardHeader><CardContent className="space-y-2">
          {detail.roles.length ? detail.roles.map((role) => <div key={role.membership_id} className="flex items-center justify-between rounded-md border p-3 text-sm"><span>{role.name} <span className="text-muted-foreground">({role.code})</span></span><Badge variant="outline">{role.membership_status}</Badge></div>) : <p className="text-sm text-muted-foreground">尚未分配角色。</p>}
        </CardContent></Card>
        <Card className="shadow-none"><CardHeader><CardTitle>外部身份安全摘要</CardTitle></CardHeader><CardContent className="space-y-2">
          {detail.external_identities.length ? detail.external_identities.map((identity) => <div key={identity.id} className="rounded-md border p-3 text-sm"><div className="flex items-center gap-2"><Badge variant="outline">{identity.provider}</Badge><span>{identity.display_name || identity.tenant_code}</span><Badge variant={identity.status === "enabled" ? "secondary" : "outline"}>{identity.status}</Badge></div><p className="mt-1 text-xs text-muted-foreground">凭据：{identity.credential_status || "不适用"} · 最近观察：{formatTime(identity.last_seen_at)}</p></div>) : <p className="text-sm text-muted-foreground">尚未关联钉钉或 ONES 身份。ONES 密码只能由本人提交。</p>}
        </CardContent></Card>
        <Card className="shadow-none"><CardHeader><CardTitle>登录会话</CardTitle></CardHeader><CardContent className="space-y-2">
          {detail.sessions.length ? detail.sessions.map((session) => <div key={session.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm"><div><p>{session.user_agent_summary || "未知客户端"}</p><p className="text-xs text-muted-foreground">{session.status} · 最近：{formatTime(session.last_seen_at)}</p></div>{current.capabilities.user_sessions_revoke && session.status === "active" ? <Button type="button" variant="outline" disabled={revoke.isPending} onClick={() => revoke.mutate(session.id)}>撤销</Button> : null}</div>) : <p className="text-sm text-muted-foreground">没有登录会话。</p>}
        </CardContent></Card>
      </div>
    </ManagementPage>
  )
}

export function RolesPage() {
  const user = useAuthenticatedUser()
  const [search, setSearch] = useState("")
  const [creating, setCreating] = useState(false)
  const query = useQuery({ queryKey: [...roleKeys.all, search], queryFn: () => listRoles(search) })
  return (
    <ManagementPage>
      <SectionHeading eyebrow="Authorization" title="角色与授权" description="管理权限来自代码目录；业务访问仅配置 Application，运行时 MCP 上限由当前 Publication 冻结。" action={<div className="flex gap-2"><Button type="button" variant="outline" onClick={() => void query.refetch()}><RefreshCwIcon />刷新</Button>{user.capabilities.roles_manage ? <Button type="button" onClick={() => setCreating((value) => !value)}><PlusIcon />新建角色</Button> : null}</div>} />
      <div className="max-w-md space-y-2"><Label htmlFor="role-search">搜索角色</Label><Input id="role-search" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
      {creating ? <CreateRoleForm onDone={() => { setCreating(false); void query.refetch() }} /> : null}
      {query.isLoading ? <ManagementLoading /> : null}<ManagementError error={query.error} retry={() => void query.refetch()} />
      <div className="grid gap-4 lg:grid-cols-2">
        {query.data?.items.map((role) => <Card key={role.id} className="shadow-none"><CardContent className="flex items-center justify-between gap-3 p-4"><div><div className="flex items-center gap-2"><ShieldIcon className="size-4" /><p className="font-medium">{role.name}</p><Badge variant={role.status === "enabled" ? "secondary" : "outline"}>{role.status === "enabled" ? "启用" : "停用"}</Badge>{role.protected ? <Badge variant="outline">系统保护</Badge> : null}</div><p className="mt-1 text-xs text-muted-foreground">{role.code} · {role.member_count} 人 · {role.admin_capability_count} 项管理权限 · {role.application_count} 个应用</p></div><Link className={buttonVariants({ variant: "outline" })} to={`/users/roles/${encodeURIComponent(role.id)}`}>配置</Link></CardContent></Card>)}
      </div>
    </ManagementPage>
  )
}

function CreateRoleForm({ onDone }: { onDone: () => void }) {
  const mutation = useMutation({ mutationFn: createRole, onSuccess: onDone })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget)
    mutation.mutate({ code: String(data.get("code") || ""), name: String(data.get("name") || ""), description: String(data.get("description") || ""), purpose_tags: String(data.get("purpose_tags") || "").split(",").map((value) => value.trim()).filter(Boolean) })
  }
  return <Card className="shadow-none"><CardHeader><CardTitle>新建角色</CardTitle></CardHeader><CardContent><form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}><Field name="code" label="角色代码" required /><Field name="name" label="角色名称" required /><div className="space-y-2 sm:col-span-2"><Label htmlFor="role-description">说明</Label><Textarea id="role-description" name="description" /></div><Field name="purpose_tags" label="用途标签（逗号分隔）" /><div className="sm:col-span-2"><MutationNotice error={mutation.error} /></div><Button type="submit">创建角色</Button></form></CardContent></Card>
}

export function RoleDetailPage() {
  const id = useParams().roleId ?? ""
  const detail = useQuery({ queryKey: roleKeys.detail(id), queryFn: () => getRole(id), enabled: Boolean(id) })
  const capabilities = useQuery({ queryKey: roleKeys.capabilities, queryFn: listAdminCapabilities })
  const applications = useQuery({ queryKey: roleKeys.applications, queryFn: listAssignableApplications })
  const users = useQuery({ queryKey: userKeys.all, queryFn: () => listUsers("") })
  if (detail.isLoading || capabilities.isLoading || applications.isLoading || users.isLoading) return <ManagementPage><ManagementLoading /></ManagementPage>
  if (!detail.data) return <ManagementPage><Back href="/users/roles" /><ManagementError error={detail.error} retry={() => void detail.refetch()} /></ManagementPage>
  return <RoleEditor key={`${detail.data.role.metadata_revision}:${detail.data.admin.revision}:${detail.data.business.revision}:${detail.data.membership.revision}`} detail={detail.data} capabilities={capabilities.data ?? []} applications={applications.data ?? []} users={users.data?.users ?? []} />
}

function RoleEditor({ detail, capabilities, applications, users }: { detail: RoleDetail; capabilities: Awaited<ReturnType<typeof listAdminCapabilities>>; applications: Awaited<ReturnType<typeof listAssignableApplications>>; users: AdminUser[] }) {
  const current = useAuthenticatedUser(); const client = useQueryClient(); const navigate = useNavigate()
  const [metadata, setMetadata] = useState({ name: detail.role.name, description: detail.role.description, purpose_tags: detail.role.purpose_tags.join(", "), status: detail.role.status })
  const [selectedCapabilities, setSelectedCapabilities] = useState(new Set(detail.admin.bindings.map((item) => item.capability_code)))
  const [selectedApplications, setSelectedApplications] = useState(new Set(detail.business.applications.map((item) => item.application_id)))
  const [newMember, setNewMember] = useState("")
  const refresh = async () => { await Promise.all([client.invalidateQueries({ queryKey: roleKeys.detail(detail.role.id) }), client.invalidateQueries({ queryKey: roleKeys.all })]) }
  const metadataMutation = useMutation({ mutationFn: () => updateRoleMetadata(detail.role.id, { expected_revision: detail.role.metadata_revision, name: metadata.name, description: metadata.description, purpose_tags: metadata.purpose_tags.split(",").map((value) => value.trim()).filter(Boolean), status: metadata.status }), onSuccess: refresh })
  const capabilityMutation = useMutation({ mutationFn: () => updateRoleCapabilities(detail.role.id, detail.admin.revision, [...selectedCapabilities]), onSuccess: refresh })
  const applicationMutation = useMutation({ mutationFn: () => updateRoleApplications(detail.role.id, detail.business.revision, [...selectedApplications]), onSuccess: refresh })
  const memberMutation = useMutation({ mutationFn: (change: { user_id: string; enabled: boolean; expected_revision: number }) => updateRoleMember(detail.role.id, detail.membership.revision, change), onSuccess: async () => { setNewMember(""); await refresh() } })
  const mutable = current.capabilities.roles_manage && !detail.role.protected
  const error = metadataMutation.error || capabilityMutation.error || applicationMutation.error || memberMutation.error
  return <ManagementPage>
    <Back href="/users/roles" /><SectionHeading eyebrow="Authorization" title={detail.role.name} description={`${detail.role.code} · ${detail.role.protected ? "系统保护角色" : "自定义角色"}`} action={<Button type="button" variant="outline" onClick={() => navigate(0)}><RefreshCwIcon />刷新</Button>} /><MutationNotice error={error} />
    <div className="grid gap-5 xl:grid-cols-2">
      <Card className="shadow-none"><CardHeader><CardTitle>基本信息</CardTitle></CardHeader><CardContent className="grid gap-4"><FieldValue label="名称" value={metadata.name} disabled={!mutable} onChange={(value) => setMetadata({ ...metadata, name: value })} /><div className="space-y-2"><Label htmlFor="role-description-edit">说明</Label><Textarea id="role-description-edit" value={metadata.description} disabled={!mutable} onChange={(event) => setMetadata({ ...metadata, description: event.target.value })} /></div><FieldValue label="用途标签" value={metadata.purpose_tags} disabled={!mutable} onChange={(value) => setMetadata({ ...metadata, purpose_tags: value })} /><div className="space-y-2"><Label htmlFor="role-status-edit">状态</Label><select id="role-status-edit" className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={metadata.status} disabled={!mutable} onChange={(event) => setMetadata({ ...metadata, status: event.target.value as "enabled" | "disabled" })}><option value="enabled">启用</option><option value="disabled">停用</option></select></div>{mutable ? <Button type="button" onClick={() => metadataMutation.mutate()}><SaveIcon />保存基本信息</Button> : <p className="text-sm text-muted-foreground">系统保护角色由代码维护，不能编辑。</p>}</CardContent></Card>
      <Card className="shadow-none"><CardHeader><CardTitle>成员</CardTitle></CardHeader><CardContent className="space-y-3">{detail.membership.members.map((member) => <div key={member.membership_id} className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"><span>{member.display_name} <span className="text-muted-foreground">@{member.username}</span></span>{current.capabilities.roles_manage ? <Button type="button" variant="outline" onClick={() => memberMutation.mutate({ user_id: member.id, enabled: false, expected_revision: member.membership_revision })}>移除</Button> : null}</div>)}{current.capabilities.roles_manage ? <div className="flex gap-2"><select aria-label="选择新增成员" className="h-9 min-w-0 flex-1 rounded-md border bg-background px-3 text-sm" value={newMember} onChange={(event) => setNewMember(event.target.value)}><option value="">选择用户</option>{users.filter((user) => !detail.membership.members.some((member) => member.id === user.id)).map((user) => <option key={user.id} value={user.id}>{user.display_name} (@{user.username})</option>)}</select><Button type="button" disabled={!newMember} onClick={() => memberMutation.mutate({ user_id: newMember, enabled: true, expected_revision: 0 })}>添加</Button></div> : null}</CardContent></Card>
      <Card className="shadow-none xl:col-span-2"><CardHeader><CardTitle>管理权限</CardTitle><p className="text-sm text-muted-foreground">权限来自服务端代码目录；勾选高阶权限时，服务端会自动补齐依赖。</p></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{detail.admin.implicit_all ? <p className="text-sm text-muted-foreground sm:col-span-2">platform-admin 自动拥有全部 Web 管理权限。</p> : capabilities.filter((item) => item.assignable).map((item) => <label key={item.code} className="flex items-start gap-3 rounded-md border p-3"><Checkbox checked={selectedCapabilities.has(item.code)} disabled={!mutable} onCheckedChange={(checked) => setSelectedCapabilities(toggle(selectedCapabilities, item.code, Boolean(checked)))} /><span className="text-sm"><span className="font-medium">{item.display_name_zh}</span><span className="mt-1 block font-mono text-xs text-muted-foreground">{item.code} · {item.risk_level}</span></span></label>)}{mutable ? <div className="sm:col-span-2 xl:col-span-3"><Button type="button" onClick={() => capabilityMutation.mutate()}><SaveIcon />保存管理权限</Button></div> : null}</CardContent></Card>
      <Card className="shadow-none xl:col-span-2"><CardHeader><CardTitle>Application 使用权限</CardTitle><p className="text-sm text-muted-foreground">这里只授权 Application；可调用 MCP Tool 的上限仍由活动 Application Publication 决定。</p></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2">{applications.map((application) => <label key={application.id} className="flex items-start gap-3 rounded-md border p-3"><Checkbox checked={selectedApplications.has(application.id)} disabled={!mutable} onCheckedChange={(checked) => setSelectedApplications(toggle(selectedApplications, application.id, Boolean(checked)))} /><span className="text-sm"><span className="font-medium">{application.name}</span><span className="mt-1 block text-xs text-muted-foreground">{application.code} · {application.project_code}</span></span></label>)}{mutable ? <div className="sm:col-span-2"><Button type="button" onClick={() => applicationMutation.mutate()}><SaveIcon />保存应用权限</Button></div> : null}</CardContent></Card>
    </div>
  </ManagementPage>
}

function toggle(source: Set<string>, value: string, checked: boolean) { const next = new Set(source); if (checked) next.add(value); else next.delete(value); return next }
function Back({ href }: { href: string }) { return <Link to={href} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeftIcon className="size-4" />返回</Link> }
function Field({ name, label, required = false, type = "text" }: { name: string; label: string; required?: boolean; type?: string }) { const id = `admin-${name}`; return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><Input id={id} name={name} type={type} required={required} /></div> }
function FieldValue({ label, value, disabled, onChange }: { label: string; value: string; disabled: boolean; onChange: (value: string) => void }) { const id = `edit-${label}`; return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><Input id={id} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} /></div> }
function formatTime(value?: string | null) { if (!value) return "无"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN") }
