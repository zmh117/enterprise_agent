import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, ShieldCheck, ShieldX } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, EmptyState, ErrorNotice, Field, Input, PageHeader } from "../components/ui";
import { api, jsonBody } from "../lib/api";
import type { Permission, Role, User } from "../lib/types";

type RoleDetail = { role: Role; members: Array<User & { membership_status: string }>; permissions: Permission[] };

export function RolesPage() {
  const client = useQueryClient();
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api<{ roles: Role[] }>("/api/admin/roles") });
  const [selectedId, setSelectedId] = useState("");
  const effectiveSelectedId = selectedId || roles.data?.roles[0]?.id || "";
  const detail = useQuery({ queryKey: ["role", effectiveSelectedId], queryFn: () => api<RoleDetail>(`/api/admin/roles/${effectiveSelectedId}`), enabled: Boolean(effectiveSelectedId) });
  const refresh = async () => { await Promise.all([client.invalidateQueries({ queryKey: ["roles"] }), client.invalidateQueries({ queryKey: ["role", effectiveSelectedId] })]); };
  return (
    <>
      <PageHeader eyebrow="Authorization" title="角色与权限策略" description="角色展开后与用户直接策略共同求值；任何命中的 deny 都优先于 allow。" />
      <CreateRole onCreated={(id) => { setSelectedId(id); void refresh(); }} />
      <div className="master-detail">
        <Card className="master-list"><div className="section-heading"><div><h2>角色</h2><p>{roles.data?.roles.length ?? 0} 个角色</p></div></div><div className="list-scroll">{roles.data?.roles.map((role) => <button key={role.id} className={`record-button ${effectiveSelectedId === role.id ? "selected" : ""}`} onClick={() => setSelectedId(role.id)}><span className="record-avatar"><ShieldCheck size={17} /></span><span><strong>{role.name}</strong><small>{role.code}</small></span><Badge tone={role.status === "enabled" ? "good" : "neutral"}>{role.status}</Badge></button>)}</div></Card>
        <div className="detail-stack">{detail.data ? <RoleDetailPanel detail={detail.data} refresh={refresh} /> : <Card><EmptyState title="选择一个角色" message="查看成员和策略矩阵。" /></Card>}</div>
      </div>
    </>
  );
}

function CreateRole({ onCreated }: { onCreated: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const mutation = useMutation({ mutationFn: () => api<{ role: Role }>("/api/admin/roles", { method: "POST", ...jsonBody(form) }), onSuccess: ({ role }) => { setOpen(false); onCreated(role.id); } });
  return <Card className="quick-create"><div><h2>定义职责角色</h2><p>角色本身不保存敏感数据，只聚合资源与 action 策略。</p></div>{open ? <form className="inline-form" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}><Input placeholder="role-code" value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} required /><Input placeholder="角色名称" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required /><Input placeholder="说明" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /><Button type="submit">创建</Button><Button variant="ghost" type="button" onClick={() => setOpen(false)}>取消</Button><ErrorNotice error={mutation.error} /></form> : <Button onClick={() => setOpen(true)}><Plus size={16} />新建角色</Button>}</Card>;
}

function RoleDetailPanel({ detail, refresh }: { detail: RoleDetail; refresh: () => Promise<void> }) {
  const [form, setForm] = useState({ resource_type: "tool", resource_code: "*", action: "use", effect: "allow" as "allow" | "deny", priority: 100 });
  const status = useMutation({ mutationFn: () => api(`/api/admin/roles/${detail.role.id}`, { method: "PUT", ...jsonBody({ expected_revision: detail.role.revision, name: detail.role.name, description: detail.role.description, status: detail.role.status === "enabled" ? "disabled" : "enabled" }) }), onSuccess: refresh });
  const policy = useMutation({ mutationFn: () => api("/api/admin/permissions", { method: "POST", ...jsonBody({ id: null, subject_type: "role", subject_code: detail.role.code, ...form, status: "enabled", expected_revision: 0 }) }), onSuccess: refresh });
  return <>
    <Card><div className="detail-title"><div className="record-avatar large"><ShieldCheck /></div><div><span className="eyebrow">RBAC role</span><h2>{detail.role.name}</h2><p>{detail.role.code} · revision {detail.role.revision}</p></div><Badge tone={detail.role.status === "enabled" ? "good" : "neutral"}>{detail.role.status}</Badge></div><div className="detail-actions"><Button variant={detail.role.status === "enabled" ? "danger" : "secondary"} onClick={() => status.mutate()}>{detail.role.status === "enabled" ? <ShieldX size={16} /> : <ShieldCheck size={16} />}{detail.role.status === "enabled" ? "停用角色" : "启用角色"}</Button></div><ErrorNotice error={status.error} /></Card>
    <Card><div className="section-heading"><div><h2>策略矩阵</h2><p>显式 deny 优先；资源编码和 action 支持通配符。</p></div></div><div className="table-wrap"><table><thead><tr><th>效果</th><th>资源</th><th>编码</th><th>Action</th><th>优先级</th><th>Revision</th></tr></thead><tbody>{detail.permissions.map((item) => <tr key={item.id}><td><Badge tone={item.effect === "allow" ? "good" : "bad"}>{item.effect}</Badge></td><td>{item.resource_type}</td><td><code>{item.resource_code}</code></td><td><code>{item.action}</code></td><td>{item.priority}</td><td>{item.revision}</td></tr>)}</tbody></table></div><form className="policy-form" onSubmit={(event: FormEvent) => { event.preventDefault(); policy.mutate(); }}><Field label="资源类型"><Input value={form.resource_type} onChange={(event) => setForm({ ...form, resource_type: event.target.value })} required /></Field><Field label="资源编码"><Input value={form.resource_code} onChange={(event) => setForm({ ...form, resource_code: event.target.value })} required /></Field><Field label="Action"><Input value={form.action} onChange={(event) => setForm({ ...form, action: event.target.value })} required /></Field><Field label="效果"><select className="input" value={form.effect} onChange={(event) => setForm({ ...form, effect: event.target.value as "allow" | "deny" })}><option value="allow">allow</option><option value="deny">deny</option></select></Field><Button type="submit">增加策略</Button></form><ErrorNotice error={policy.error} /></Card>
    <Card><div className="section-heading"><div><h2>成员</h2><p>成员分配在用户详情中完成，避免脱离目标用户上下文。</p></div></div><div className="member-grid">{detail.members.map((member) => <div className="member-card" key={member.id}><span className="record-avatar">{member.display_name.slice(0, 1)}</span><span><strong>{member.display_name}</strong><small>{member.username}</small></span><Badge tone={member.status === "enabled" ? "good" : "neutral"}>{member.status}</Badge></div>)}</div></Card>
  </>;
}
