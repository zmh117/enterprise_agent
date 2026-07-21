import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileClock, RotateCcw, Save, Send, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge, Button, Card, ErrorNotice, Field, Input, PageHeader, formatTime } from "../../../shared/presentation/ui";
import { agentService } from "../application/services";
import type { AgentConfig, AgentPayload, AgentPublication, ConnectorSummary } from "../domain/models";

const AGENT = "default-diagnostic-agent";

export function AgentPage() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["agent", AGENT], queryFn: () => agentService.get(AGENT) });
  const publications = useQuery({ queryKey: ["agent-publications", AGENT], queryFn: () => agentService.listPublications(AGENT) });
  const refresh = async () => { await Promise.all([client.invalidateQueries({ queryKey: ["agent", AGENT] }), client.invalidateQueries({ queryKey: ["agent-publications", AGENT] })]); };
  const agent = query.data?.agent;
  const initialDraft = agent?.draft?.config ?? agent?.current_publication?.snapshot;
  if (!agent || !initialDraft) return <><PageHeader eyebrow="Agent release control" title="默认诊断 Agent" description="正在读取固定发布配置…" /><ErrorNotice error={query.error} /></>;
  const editorKey = `${agent.draft?.id ?? "published"}:${agent.current_publication?.id ?? "none"}`;
  return <AgentEditor key={editorKey} agent={agent} initialDraft={initialDraft} publications={publications.data?.publications ?? []} refresh={refresh} />;
}

function AgentEditor({ agent, initialDraft, publications, refresh }: { agent: AgentPayload; initialDraft: AgentConfig; publications: AgentPublication[]; refresh: () => Promise<void> }) {
  const [draft, setDraft] = useState<AgentConfig>(initialDraft);
  const [confirmation, setConfirmation] = useState<{ kind: "publish"; revisionId: string; revision: number } | { kind: "rollback"; publicationId: string; revision: number } | null>(null);
  const save = useMutation({ mutationFn: () => agentService.saveDraft(AGENT, agent.draft?.revision ?? 0, draft), onSuccess: refresh });
  const validate = useMutation({ mutationFn: (revisionId: string) => agentService.validate(AGENT, revisionId), onSuccess: refresh });
  const publish = useMutation({ mutationFn: (revisionId: string) => agentService.publish(AGENT, revisionId), onSuccess: refresh });
  const rollback = useMutation({ mutationFn: (publicationId: string) => agentService.rollback(AGENT, publicationId), onSuccess: refresh });
  const errors = save.error || validate.error || publish.error || rollback.error;
  const revision = agent.draft;
  const isValid = revision?.validation?.valid === true;
  return <>
    <PageHeader eyebrow="Agent release control" title={agent.definition.name} description="第一版 Web 固定管理 default-diagnostic-agent，不提供其它 Agent 的创建、删除或切换入口。" actions={<><Badge tone={agent.definition.status === "enabled" ? "good" : "neutral"}>{agent.definition.status}</Badge><Button variant="secondary" onClick={() => save.mutate()} disabled={save.isPending}><Save size={16} />保存草稿</Button></>} />
    <div className="agent-status-strip"><div><span>草稿 revision</span><strong>{revision?.revision ?? 0}</strong></div><div><span>当前发布</span><strong>r{agent.current_publication?.revision ?? "—"}</strong></div><div><span>配置 hash</span><code>{agent.current_publication?.config_hash.slice(0, 12) ?? "—"}</code></div><div><ShieldCheck size={18} /><span>平台安全层始终强制</span></div></div>
    <ErrorNotice error={errors} />
    {revision?.validation?.errors?.length ? <div className="notice notice-error"><strong>草稿校验未通过</strong>{revision.validation.errors.map((item) => <span key={`${item.field}-${item.message}`}>{item.field}：{item.message}</span>)}</div> : null}
    <div className="agent-grid">
      <div className="detail-stack">
        <Card><div className="section-heading"><div><h2>职责与业务指令</h2><p>业务层优先级低于平台安全、权限和只读策略。</p></div></div><Field label="业务角色"><Input value={draft.business_role} onChange={(event) => setDraft({ ...draft, business_role: event.target.value })} /></Field><Field label="业务指令" hint="不得要求绕过权限、写数据库、执行 Bash 或泄露密钥。"><textarea className="input textarea" value={draft.business_instructions} onChange={(event) => setDraft({ ...draft, business_instructions: event.target.value })} /></Field></Card>
        <Card><div className="section-heading"><div><h2>模型与执行限制</h2><p>只选择已注册模型；凭据由服务端 runtime config/secret 解析。</p></div></div><div className="form-grid"><Field label="模型"><select className="input" value={draft.model_policy.model} onChange={(event) => setDraft({ ...draft, model_policy: { model: event.target.value } })}>{agent.catalog.models.includes(draft.model_policy.model) ? null : <option value={draft.model_policy.model} disabled>{draft.model_policy.model}（当前未注册）</option>}{agent.catalog.models.map((model) => <option key={model}>{model}</option>)}</select></Field><Field label="最大轮次"><Input type="number" min={1} max={100} value={draft.execution.max_turns} onChange={(event) => setDraft({ ...draft, execution: { ...draft.execution, max_turns: Number(event.target.value) } })} /></Field><Field label="超时（秒）"><Input type="number" min={10} max={3600} value={draft.execution.timeout_seconds} onChange={(event) => setDraft({ ...draft, execution: { ...draft.execution, timeout_seconds: Number(event.target.value) } })} /></Field><Field label="默认项目"><Input value={draft.routing.project_code} onChange={(event) => setDraft({ ...draft, routing: { project_code: event.target.value } })} /></Field></div></Card>
        <AssignmentCard title="只读工具" description="最终可用集合仍需同时通过代码注册、启用、用户权限与平台数据范围。" values={agent.catalog.tools} selected={draft.tools} onChange={(tools) => setDraft({ ...draft, tools })} />
        <AssignmentCard title="Skills" description="仅能选择服务端已安装的 Skill。" values={agent.catalog.skills} selected={draft.skills} onChange={(skills) => setDraft({ ...draft, skills })} empty="当前没有可分配 Skill" />
        <ConnectorCard connectors={agent.catalog.connectors} draft={draft} onChange={setDraft} />
      </div>
      <aside className="agent-rail">
        <Card><div className="section-heading"><div><h2>发布检查</h2><p>保存后先校验，再发布不可变快照。</p></div></div><div className="release-steps"><div className={revision ? "done" : ""}><Save size={16} /><span>保存 revision</span></div><div className={isValid ? "done" : ""}><CheckCircle2 size={16} /><span>服务端校验</span></div><div className={agent.current_publication?.revision === revision?.revision ? "done" : ""}><Send size={16} /><span>创建 publication</span></div></div><Button variant="secondary" disabled={!revision} onClick={() => revision && validate.mutate(revision.id)}><CheckCircle2 size={16} />校验草稿</Button><Button disabled={!revision || !isValid} onClick={() => revision && setConfirmation({ kind: "publish", revisionId: revision.id, revision: revision.revision })}><Send size={16} />发布当前草稿</Button></Card>
        <Card><div className="section-heading"><div><h2>有效配置预览</h2><p>运行中 job 使用自己的固定 snapshot。</p></div></div><pre className="config-preview">{JSON.stringify({ publication_id: agent.current_publication?.id, revision: agent.current_publication?.revision, config_hash: agent.current_publication?.config_hash, platform_enforced: ["read_only_tools", "authorization", "no_builtin_mutation_tools"] }, null, 2)}</pre></Card>
        <Card><div className="section-heading"><div><h2>发布历史</h2><p>回滚只移动当前指针，不修改历史快照。</p></div><FileClock size={19} /></div><div className="publication-list">{publications.map((item) => <div key={item.id} className={`publication-item ${item.id === agent.current_publication?.id ? "current" : ""}`}><div><strong>revision {item.revision}</strong><span>{formatTime(item.published_at)} · {item.published_by}</span><code>{item.config_hash.slice(0, 12)}</code></div>{item.id === agent.current_publication?.id ? <Badge tone="good">current</Badge> : <Button variant="ghost" onClick={() => setConfirmation({ kind: "rollback", publicationId: item.id, revision: item.revision })}><RotateCcw size={14} />回滚</Button>}</div>)}</div></Card>
      </aside>
    </div>
    {confirmation ? <div className="dialog-backdrop" role="presentation"><div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="agent-confirm-title"><span className="eyebrow">Release confirmation</span><h2 id="agent-confirm-title">{confirmation.kind === "publish" ? `发布 revision ${confirmation.revision}` : `回滚到 revision ${confirmation.revision}`}</h2><p>{confirmation.kind === "publish" ? "发布后，新任务会固定使用这个不可变快照；已经创建的任务不受影响。" : "回滚只移动当前发布指针；已运行、重试中和历史任务仍保持原 publication。"}</p><div className="dialog-actions"><Button variant="ghost" onClick={() => setConfirmation(null)}>取消</Button><Button onClick={() => { if (confirmation.kind === "publish") publish.mutate(confirmation.revisionId); else rollback.mutate(confirmation.publicationId); setConfirmation(null); }}>{confirmation.kind === "publish" ? "确认发布" : "确认回滚"}</Button></div></div></div> : null}
  </>;
}

function AssignmentCard({ title, description, values, selected, onChange, empty }: { title: string; description: string; values: string[]; selected: string[]; onChange: (next: string[]) => void; empty?: string }) {
  return <Card><div className="section-heading"><div><h2>{title}</h2><p>{description}</p></div><Badge tone="neutral">{selected.length} 已选择</Badge></div>{values.length ? <div className="check-grid">{values.map((value) => <label className="check-card" key={value}><input type="checkbox" checked={selected.includes(value)} onChange={(event) => onChange(event.target.checked ? [...selected, value] : selected.filter((item) => item !== value))} /><span><strong>{value}</strong><small>registered & enabled</small></span></label>)}</div> : <p className="muted">{empty}</p>}</Card>;
}

function ConnectorCard({ connectors, draft, onChange }: { connectors: ConnectorSummary[]; draft: AgentConfig; onChange: (next: AgentConfig) => void }) {
  const ingress = useMemo(() => connectors.filter((item) => Boolean(item.allow_ingress)), [connectors]);
  const delivery = useMemo(() => connectors.filter((item) => Boolean(item.allow_delivery)), [connectors]);
  const choices = (direction: "ingress" | "delivery", values: ConnectorSummary[]) => <div className="check-grid">{values.map((connector) => { const selected = draft.channels[direction].includes(connector.id); return <label className="check-card" key={`${direction}-${connector.id}`}><input type="checkbox" checked={selected} onChange={(event) => onChange({ ...draft, channels: { ...draft.channels, [direction]: event.target.checked ? [...draft.channels[direction], connector.id] : draft.channels[direction].filter((item) => item !== connector.id) } })} /><span><strong>{connector.name}</strong><small>{connector.connector_type}</small></span></label>; })}</div>;
  return <Card><div className="section-heading"><div><h2>Channel / Delivery</h2><p>入口和结果投递分别绑定，不能混用 connector 方向。</p></div></div><h3 className="subheading">Ingress</h3>{choices("ingress", ingress)}<h3 className="subheading">Delivery</h3>{choices("delivery", delivery)}</Card>;
}
