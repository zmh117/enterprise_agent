import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, MonitorSmartphone, Plus, RefreshCw, UserRoundCheck, UserRoundX } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { Badge, Button, Card, EmptyState, ErrorNotice, Field, Input, PageHeader, formatTime } from "../../../shared/presentation/ui";
import { authorizationService } from "../../authorization/application/services";
import type { Role } from "../../authorization/domain/models";
import { identityService, type UserDetail } from "../application/services";
import type { DingTalkTenant, ExternalIdentity, LoginSession, User } from "../domain/models";

export function UsersPage() {
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: identityService.listUsers });
  const roles = useQuery({ queryKey: ["roles"], queryFn: authorizationService.listRoles });
  const tenants = useQuery({ queryKey: ["dingtalk-tenants"], queryFn: identityService.listTenants });
  const [selectedId, setSelectedId] = useState("");
  const effectiveSelectedId = selectedId || users.data?.users[0]?.id || "";
  const detail = useQuery({
    queryKey: ["user", effectiveSelectedId],
    queryFn: () => identityService.getUser(effectiveSelectedId),
    enabled: Boolean(effectiveSelectedId),
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["users"] }),
      queryClient.invalidateQueries({ queryKey: ["user", effectiveSelectedId] }),
    ]);
  };

  return (
    <>
      <PageHeader eyebrow="Identity control" title="用户与外部身份" description="内部用户是唯一权限主体；钉钉 senderStaffId 只负责解析到内部用户。" actions={<Button variant="secondary" onClick={refresh}><RefreshCw size={16} />刷新</Button>} />
      <CreateUser onCreated={(id) => { setSelectedId(id); void refresh(); }} />
      <div className="master-detail">
        <Card className="master-list">
          <div className="section-heading"><div><h2>内部用户</h2><p>{users.data?.users.length ?? 0} 个用户</p></div></div>
          <div className="list-scroll">
            {users.data?.users.map((user) => (
              <button key={user.id} className={`record-button ${effectiveSelectedId === user.id ? "selected" : ""}`} onClick={() => setSelectedId(user.id)}>
                <span className="record-avatar">{user.display_name.slice(0, 1)}</span><span><strong>{user.display_name}</strong><small>{user.username}</small></span><Badge tone={user.status === "enabled" ? "good" : "neutral"}>{user.status}</Badge>
              </button>
            ))}
          </div>
        </Card>
        <div className="detail-stack">
          {detail.data ? <UserDetailPanel detail={detail.data} allRoles={roles.data?.roles ?? []} tenants={tenants.data?.tenants ?? []} refresh={refresh} /> : <Card><EmptyState title="选择一个用户" message="查看角色、钉钉身份和活动会话。" /></Card>}
        </div>
      </div>
    </>
  );
}

function CreateUser({ onCreated }: { onCreated: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ username: "", display_name: "", email: "", password: "" });
  const mutation = useMutation({
    mutationFn: () => identityService.createUser({ ...form, password: form.password || null }),
    onSuccess: ({ user }) => { setOpen(false); setForm({ username: "", display_name: "", email: "", password: "" }); onCreated(user.id); },
  });
  return (
    <Card className="quick-create">
      <div><h2>录入内部用户</h2><p>不会根据昵称、手机号或邮箱自动绑定钉钉身份。</p></div>
      {open ? <form className="inline-form" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}><Input placeholder="用户名" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} required /><Input placeholder="显示名称" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} required /><Input placeholder="邮箱（可选）" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /><Input type="password" minLength={12} placeholder="初始密码（可选，至少12位）" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /><Button type="submit" disabled={mutation.isPending}>创建</Button><Button type="button" variant="ghost" onClick={() => setOpen(false)}>取消</Button><ErrorNotice error={mutation.error} /></form> : <Button onClick={() => setOpen(true)}><Plus size={16} />新建用户</Button>}
    </Card>
  );
}

function UserDetailPanel({ detail, allRoles, tenants, refresh }: { detail: UserDetail; allRoles: Role[]; tenants: DingTalkTenant[]; refresh: () => Promise<void> }) {
  const { user } = detail;
  const roleIds = useMemo(() => new Set(detail.roles.map((role) => role.id)), [detail.roles]);
  const [binding, setBinding] = useState({ tenant: tenants[0]?.tenant_code ?? "", connector: tenants[0]?.connector_id ?? "", subject: "", display: "" });
  const selectedConnector = binding.connector || tenants[0]?.connector_id || "";
  const selectedTenant = binding.tenant || tenants[0]?.tenant_code || "";
  const update = useMutation({ mutationFn: (status: User["status"]) => identityService.updateUserStatus(user, status), onSuccess: refresh });
  const membership = useMutation({ mutationFn: ({ role, enabled }: { role: Role; enabled: boolean }) => {
    const assigned = detail.roles.find((item) => item.id === role.id);
    return identityService.setRole(user.id, role, enabled, assigned?.membership_revision ?? 0);
  }, onSuccess: refresh });
  const bind = useMutation({ mutationFn: () => identityService.bindDingTalk(user, { tenant_code: selectedTenant, connector_id: selectedConnector, external_subject_id: binding.subject, display_name: binding.display }), onSuccess: async () => { setBinding({ tenant: selectedTenant, connector: selectedConnector, subject: "", display: "" }); await refresh(); } });
  const identityStatus = useMutation({ mutationFn: (identity: ExternalIdentity) => identityService.toggleIdentity(identity), onSuccess: refresh });
  const revoke = useMutation({ mutationFn: (session: LoginSession) => identityService.revokeSession(user.id, session.id), onSuccess: refresh });
  const errors = update.error || membership.error || bind.error || identityStatus.error || revoke.error;
  return (
    <>
      <Card><div className="detail-title"><div className="record-avatar large">{user.display_name.slice(0, 1)}</div><div><span className="eyebrow">Internal principal</span><h2>{user.display_name}</h2><p>{user.username} · revision {user.revision}</p></div><Badge tone={user.status === "enabled" ? "good" : "neutral"}>{user.status}</Badge></div><div className="detail-actions"><Button variant={user.status === "enabled" ? "danger" : "secondary"} onClick={() => update.mutate(user.status === "enabled" ? "disabled" : "enabled")}>{user.status === "enabled" ? <UserRoundX size={16} /> : <UserRoundCheck size={16} />}{user.status === "enabled" ? "停用用户" : "启用用户"}</Button></div><ErrorNotice error={errors} /></Card>
      <Card><div className="section-heading"><div><h2>角色分配</h2><p>停用角色或 membership 后立即不再参与授权。</p></div></div><div className="check-grid">{allRoles.map((role) => <label className="check-card" key={role.id}><input type="checkbox" checked={roleIds.has(role.id)} onChange={(event) => membership.mutate({ role, enabled: event.target.checked })} /><span><strong>{role.name}</strong><small>{role.code}</small></span><Badge tone={role.status === "enabled" ? "good" : "neutral"}>{role.status}</Badge></label>)}</div></Card>
      <Card><div className="section-heading"><div><h2>钉钉身份</h2><p>选择受信 tenant/connector，并录入 senderStaffId。</p></div><Link2 size={20} /></div><div className="identity-list">{detail.identities.map((identity) => <div className="identity-row" key={identity.id}><div><strong>{identity.display_name || identity.external_subject_id}</strong><span>{identity.tenant_code} · {identity.external_subject_id}</span><small>最近出现：{formatTime(identity.last_seen_at)}</small></div><Badge tone={identity.status === "enabled" ? "good" : "neutral"}>{identity.status}</Badge><Button variant="ghost" onClick={() => identityStatus.mutate(identity)}>{identity.status === "enabled" ? "停用" : "启用"}</Button></div>)}</div><form className="binding-form" onSubmit={(event: FormEvent) => { event.preventDefault(); bind.mutate(); }}><Field label="钉钉企业"><select className="input" value={selectedConnector} onChange={(event) => { const tenant = tenants.find((item) => item.connector_id === event.target.value); setBinding({ ...binding, connector: event.target.value, tenant: tenant?.tenant_code ?? "" }); }}>{tenants.map((tenant) => <option key={tenant.connector_id} value={tenant.connector_id}>{tenant.name} · {tenant.tenant_code}</option>)}</select></Field><Field label="senderStaffId"><Input value={binding.subject} onChange={(event) => setBinding({ ...binding, subject: event.target.value })} required /></Field><Field label="显示备注"><Input value={binding.display} onChange={(event) => setBinding({ ...binding, display: event.target.value })} /></Field><Button type="submit" disabled={!selectedConnector || bind.isPending}>确认绑定</Button></form></Card>
      <Card><div className="section-heading"><div><h2>登录会话</h2><p>管理员可立即撤销指定设备的服务端 session。</p></div><MonitorSmartphone size={20} /></div><div className="table-wrap"><table><thead><tr><th>状态</th><th>最后使用</th><th>过期</th><th>设备摘要</th><th /></tr></thead><tbody>{detail.sessions.map((session) => <tr key={session.id}><td><Badge tone={session.status === "active" ? "good" : "neutral"}>{session.status}</Badge></td><td>{formatTime(session.last_seen_at)}</td><td>{formatTime(session.idle_expires_at)}</td><td>{session.user_agent_summary || "—"}</td><td>{session.status === "active" ? <Button variant="ghost" onClick={() => revoke.mutate(session)}>撤销</Button> : null}</td></tr>)}</tbody></table></div></Card>
    </>
  );
}
