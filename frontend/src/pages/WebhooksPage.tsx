import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowLeft, CheckCircle2, Eye, FileClock, Plus, RotateCcw, Save, Send, ShieldAlert, Webhook } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useAuth } from "../auth";
import { Badge, Button, Card, EmptyState, ErrorNotice, Field, Input, PageHeader, formatTime } from "../components/ui";
import { api, jsonBody } from "../lib/api";
import type { Connector, WebhookEvent, WebhookPublication, WebhookRevision, WebhookTriggerConfig, WebhookTriggerDefinition, WebhookTriggerPayload } from "../lib/types";

type Catalog = {
  agent: { code: string; name: string; publication_id: string; revision: number; config_hash: string; read_only_tools: string[] };
  connectors: Connector[];
};

const DEFAULT_SAMPLE = JSON.stringify({
  status: "firing",
  groupKey: "order-service-prod",
  commonLabels: { ea_project_code: "default", ea_environment: "prod", ea_base: "guanlan", ea_workshop: "GL001", ea_service: "order-service" },
  commonAnnotations: { summary: "Order service error rate is high" },
  alerts: [{ status: "firing", fingerprint: "example-001" }],
}, null, 2);

export function WebhooksPage() {
  const { user } = useAuth();
  const query = useQuery({ queryKey: ["webhook-triggers"], queryFn: () => api<{ triggers: WebhookTriggerDefinition[] }>("/api/admin/webhook-triggers") });
  const triggers = query.data?.triggers ?? [];
  return <>
    <PageHeader eyebrow="Managed event ingress" title="Webhook 触发器" description="第三方系统只提交不可信事件；Trigger 固定服务账号、诊断 Agent、只读工具范围和钉钉投递目标。" actions={user?.capabilities.webhook_edit ? <Link className="button button-primary" to="/admin/webhooks/new"><Plus size={16} />新建 Trigger</Link> : undefined} />
    <ErrorNotice error={query.error} />
    <Card>
      <div className="section-heading"><div><h2>已发布入口</h2><p>public ID 不是凭证；认证值只从 secret reference 解析。</p></div><Badge tone="neutral">{triggers.length} triggers</Badge></div>
      {triggers.length ? <div className="webhook-list">{triggers.map((trigger) => <WebhookListItem key={trigger.id} trigger={trigger} />)}</div> : <EmptyState title="还没有 Webhook Trigger" message="创建后先配置最小权限，再校验并发布不可变快照。" />}
    </Card>
  </>;
}

function WebhookListItem({ trigger }: { trigger: WebhookTriggerDefinition }) {
  const tone = trigger.status === "enabled" && trigger.current_publication_id ? "good" : trigger.status === "disabled" ? "neutral" : "warn";
  return <Link className="webhook-list-item" to={`/admin/webhooks/${trigger.code}`}>
    <div className="webhook-icon"><Webhook size={18} /></div>
    <div><strong>{trigger.name}</strong><span>{trigger.code} · {trigger.trigger_type}</span><small>{trigger.connector_id}</small></div>
    <div><span>Agent publication</span><strong>{trigger.agent_publication_id ?? "未发布"}</strong></div>
    <div><span>服务账号</span><strong>{trigger.service_account_username}</strong></div>
    <div><span>最近事件</span><strong>{trigger.recent_event_status ?? "暂无"}</strong><small>{trigger.recent_event_at ? formatTime(trigger.recent_event_at) : `${trigger.event_count ?? 0} events`}</small></div>
    <Badge tone={tone}>{trigger.status}</Badge>
  </Link>;
}

export function WebhookEditorPage() {
  const { code } = useParams();
  const catalogQuery = useQuery({ queryKey: ["webhook-catalog"], queryFn: () => api<Catalog>("/api/admin/webhook-triggers/catalog") });
  const triggerQuery = useQuery({
    queryKey: ["webhook-trigger", code],
    queryFn: () => api<{ trigger: WebhookTriggerPayload }>(`/api/admin/webhook-triggers/${code}`),
    enabled: Boolean(code),
  });
  if (!catalogQuery.data || (code && !triggerQuery.data)) return <><PageHeader eyebrow="Managed event ingress" title="Webhook Trigger" description="正在读取发布配置…" /><ErrorNotice error={catalogQuery.error || triggerQuery.error} /></>;
  const trigger = triggerQuery.data?.trigger;
  const initial = trigger?.draft?.config ?? trigger?.current_publication?.snapshot ?? defaultConfig(catalogQuery.data);
  const editorKey = `${code ?? "new"}:${trigger?.draft?.id ?? "none"}:${catalogQuery.data.agent.publication_id}`;
  return <WebhookEditor key={editorKey} code={code} catalog={catalogQuery.data} trigger={trigger} initial={initial} />;
}

function WebhookEditor({ code, catalog, trigger, initial }: { code?: string; catalog: Catalog; trigger?: WebhookTriggerPayload; initial: WebhookTriggerConfig }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState(trigger?.definition.name ?? "");
  const [newCode, setNewCode] = useState("");
  const [config, setConfig] = useState<WebhookTriggerConfig>(initial);
  const [sample, setSample] = useState(DEFAULT_SAMPLE);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [advancedError, setAdvancedError] = useState("");
  const [confirm, setConfirm] = useState<"publish" | "rotate" | null>(null);
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["webhook-trigger", code] }),
      queryClient.invalidateQueries({ queryKey: ["webhook-triggers"] }),
    ]);
  };
  const ingressConnectors = useMemo(() => catalog.connectors.filter((item) => Boolean(item.allow_ingress)), [catalog.connectors]);
  const deliveryConnectors = useMemo(() => catalog.connectors.filter((item) => Boolean(item.allow_delivery)), [catalog.connectors]);
  const create = useMutation({
    mutationFn: () => api<{ trigger: { definition: WebhookTriggerDefinition } }>("/api/admin/webhook-triggers", { method: "POST", ...jsonBody({ code: newCode, name, trigger_type: config.adapter === "grafana_alertmanager_v1" ? "grafana" : "generic", connector_id: ingressConnectors[0]?.id ?? "", config }) }),
    onSuccess: (result) => navigate(`/admin/webhooks/${result.trigger.definition.code}`),
  });
  const save = useMutation({
    mutationFn: () => api<{ revision: WebhookRevision }>(`/api/admin/webhook-triggers/${code}/revisions`, { method: "POST", ...jsonBody({ expected_revision: trigger?.draft?.revision ?? 0, config }) }),
    onSuccess: refresh,
  });
  const validate = useMutation({
    mutationFn: (revisionId: string) => api<{ revision: WebhookRevision }>(`/api/admin/webhook-triggers/${code}/revisions/${revisionId}/validate`, { method: "POST" }),
    onSuccess: refresh,
  });
  const previewMutation = useMutation({
    mutationFn: ({ revisionId, payload }: { revisionId: string; payload: Record<string, unknown> }) => api<{ preview: Record<string, unknown> }>(`/api/admin/webhook-triggers/${code}/revisions/${revisionId}/preview`, { method: "POST", ...jsonBody({ sample_payload: payload }) }),
    onSuccess: (result) => setPreview(result.preview),
  });
  const publish = useMutation({
    mutationFn: (revisionId: string) => api<{ publication: WebhookPublication }>(`/api/admin/webhook-triggers/${code}/revisions/${revisionId}/publish`, { method: "POST" }),
    onSuccess: refresh,
  });
  const rotate = useMutation({
    mutationFn: () => api(`/api/admin/webhook-triggers/${code}/rotate-public-id`, { method: "POST", ...jsonBody({ expected_revision: trigger?.definition.revision, confirm: true }) }),
    onSuccess: refresh,
  });
  const rollback = useMutation({
    mutationFn: (publicationId: string) => api(`/api/admin/webhook-triggers/${code}/publications/${publicationId}/rollback`, { method: "POST", ...jsonBody({ publication_id: publicationId, expected_revision: trigger?.definition.revision }) }),
    onSuccess: refresh,
  });
  const setEnabled = useMutation({
    mutationFn: (enabled: boolean) => api(`/api/admin/webhook-triggers/${code}`, { method: "PATCH", ...jsonBody({ expected_revision: trigger?.definition.revision, name, connector_id: trigger?.definition.connector_id, status: enabled ? "enabled" : "disabled" }) }),
    onSuccess: refresh,
  });
  const setServiceAccount = useMutation({
    mutationFn: (enabled: boolean) => api(`/api/admin/webhook-triggers/${code}/service-account`, { method: "PUT", ...jsonBody({ expected_revision: trigger?.definition.revision, enabled }) }),
    onSuccess: refresh,
  });
  const mutationError = create.error || save.error || validate.error || previewMutation.error || publish.error || rotate.error || rollback.error || setEnabled.error || setServiceAccount.error;
  const revision = trigger?.draft;
  const canEdit = Boolean(user?.capabilities.webhook_edit);
  const updateJson = (field: "variables" | "filters" | "routing", value: string) => {
    try {
      const parsed = JSON.parse(value);
      setAdvancedError("");
      if (field === "routing") setConfig((current) => ({ ...current, routing: parsed }));
      else setConfig((current) => ({ ...current, mapping: { ...current.mapping, [field]: parsed } }));
    } catch {
      setAdvancedError(`${field} 必须是有效 JSON`);
    }
  };
  const runPreview = () => {
    if (!revision) return;
    try {
      const payload = JSON.parse(sample) as Record<string, unknown>;
      setAdvancedError("");
      previewMutation.mutate({ revisionId: revision.id, payload });
    } catch {
      setAdvancedError("测试 payload 必须是 JSON object");
    }
  };
  if (code && !trigger) return null;
  return <>
    <PageHeader eyebrow="Trigger release control" title={code ? trigger?.definition.name ?? "Webhook Trigger" : "新建 Webhook Trigger"} description="外部 payload 不能选择 Agent、工具、服务账号、connector 或投递 URL；这些值只来自发布快照。" actions={<><Link className="button button-ghost" to="/admin/webhooks"><ArrowLeft size={15} />返回列表</Link>{code ? <Link className="button button-secondary" to={`/admin/webhooks/${code}/events`}><Activity size={15} />事件记录</Link> : null}</>} />
    <ErrorNotice error={mutationError} />
    {advancedError ? <div className="notice notice-error"><strong>{advancedError}</strong></div> : null}
    {revision?.validation.errors?.length ? <div className="notice notice-error"><strong>校验未通过</strong>{revision.validation.errors.map((error) => <span key={`${error.field}-${error.message}`}>{error.field}：{error.message}</span>)}</div> : null}
    {code && trigger ? <TriggerStatus trigger={trigger} onEnable={(enabled) => setEnabled.mutate(enabled)} onServiceAccount={(enabled) => setServiceAccount.mutate(enabled)} canEdit={canEdit} canManageService={Boolean(user?.capabilities.webhook_manage_service_account)} /> : null}
    <div className="agent-grid webhook-editor-grid">
      <div className="detail-stack">
        <Card><div className="section-heading"><div><h2>入口与认证</h2><p>secret reference 在运行时解析，页面永不读取凭证值。</p></div><ShieldAlert size={19} /></div><div className="form-grid webhook-form-grid">{code ? null : <Field label="稳定 code"><Input value={newCode} onChange={(event) => setNewCode(event.target.value)} disabled={!canEdit} /></Field>}<Field label="名称"><Input value={name} onChange={(event) => setName(event.target.value)} disabled={!canEdit} /></Field><Field label="Adapter"><select className="input" value={config.adapter} disabled={!canEdit} onChange={(event) => setConfig({ ...config, adapter: event.target.value as WebhookTriggerConfig["adapter"] })}><option value="grafana_alertmanager_v1">Grafana Alertmanager</option><option value="generic_json_v1">通用 JSON</option></select></Field><Field label="认证"><select className="input" value={config.authentication.type} disabled={!canEdit} onChange={(event) => setConfig({ ...config, authentication: { ...config.authentication, type: event.target.value as WebhookTriggerConfig["authentication"]["type"] } })}><option value="bearer_v1">Bearer</option><option value="hmac_sha256_v1">HMAC-SHA256</option></select></Field><Field label="Secret reference"><Input value={config.authentication.secret_ref} disabled={!canEdit} onChange={(event) => setConfig({ ...config, authentication: { ...config.authentication, secret_ref: event.target.value } })} /></Field>{code ? <Field label="Ingress connector"><Input value={trigger?.definition.connector_id ?? ""} disabled /></Field> : <Field label="Ingress connector"><select className="input" value={ingressConnectors[0]?.id ?? ""} disabled>{ingressConnectors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>}</div></Card>
        <Card><div className="section-heading"><div><h2>映射、过滤与范围</h2><p>仅支持 JSON Pointer、受限 AND 条件、变量模板和 routing allowlist，不执行脚本。</p></div></div><Field label="消息模板"><textarea className="input" rows={3} value={config.mapping.message_template} disabled={!canEdit} onChange={(event) => setConfig({ ...config, mapping: { ...config.mapping, message_template: event.target.value } })} /></Field>{config.adapter === "generic_json_v1" ? <Field label="Event ID JSON Pointer"><Input value={config.mapping.event_id_pointer} disabled={!canEdit} onChange={(event) => setConfig({ ...config, mapping: { ...config.mapping, event_id_pointer: event.target.value } })} /></Field> : null}<AdvancedJsonField label="声明变量 JSON" value={config.mapping.variables} onChange={(value) => updateJson("variables", value)} disabled={!canEdit} /><AdvancedJsonField label="过滤条件 JSON" value={config.mapping.filters} onChange={(value) => updateJson("filters", value)} disabled={!canEdit} /><AdvancedJsonField label="Routing policy JSON" value={config.routing} onChange={(value) => updateJson("routing", value)} disabled={!canEdit} /></Card>
        <Card><div className="section-heading"><div><h2>固定 Agent 与 Delivery</h2><p>第一版 UI 只开放默认诊断 Agent；有效工具由 Agent publication 与服务账号 RBAC 求交集。</p></div></div><div className="agent-pin"><div><span>Agent</span><strong>{catalog.agent.name}</strong><code>{catalog.agent.publication_id} · r{catalog.agent.revision}</code></div><div><span>只读工具</span><div className="tool-chip-row">{catalog.agent.read_only_tools.map((tool) => <Badge key={tool} tone="neutral">{tool}</Badge>)}</div></div></div><div className="form-grid webhook-form-grid"><Field label="Delivery connector"><select className="input" value={config.delivery.connector_id} disabled={!canEdit} onChange={(event) => setConfig({ ...config, delivery: { ...config.delivery, connector_id: event.target.value } })}>{deliveryConnectors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="Delivery type"><select className="input" value={config.delivery.type} disabled={!canEdit} onChange={(event) => setConfig({ ...config, delivery: { ...config.delivery, type: event.target.value } })}><option value="dingtalk_webhook_robot">钉钉 Webhook 机器人</option><option value="dingtalk_enterprise_robot">钉钉企业机器人</option></select></Field><Field label="固定目标 ID"><Input value={Object.values(config.delivery.target)[0] ?? ""} disabled={!canEdit} onChange={(event) => setConfig({ ...config, delivery: { ...config.delivery, target: config.delivery.type === "dingtalk_webhook_robot" ? { webhook_id: event.target.value } : { open_conversation_id: event.target.value } } })} /></Field><Field label="每分钟请求"><Input type="number" value={config.limits.requests_per_minute} disabled={!canEdit} onChange={(event) => setConfig({ ...config, limits: { ...config.limits, requests_per_minute: Number(event.target.value) } })} /></Field></div></Card>
        <Card><div className="section-heading"><div><h2>安全预览</h2><p>只执行提取、过滤和范围校验；不会写事件、创建 job、调用 Agent 或发送钉钉。</p></div><Eye size={19} /></div><textarea className="input webhook-sample" value={sample} onChange={(event) => setSample(event.target.value)} /><div className="detail-actions"><Button variant="secondary" onClick={runPreview} disabled={!revision}><Eye size={15} />运行无副作用预览</Button></div>{preview ? <pre className="config-preview">{JSON.stringify(preview, null, 2)}</pre> : null}</Card>
      </div>
      <aside className="agent-rail"><Card><div className="section-heading"><div><h2>发布流程</h2><p>草稿保存、服务端校验、显式发布。</p></div></div>{code ? <><Button variant="secondary" disabled={!canEdit || advancedError !== ""} onClick={() => save.mutate()}><Save size={15} />保存新 revision</Button><Button variant="secondary" disabled={!revision || !canEdit} onClick={() => revision && validate.mutate(revision.id)}><CheckCircle2 size={15} />校验 revision</Button><Button disabled={!revision?.validation.valid || !user?.capabilities.webhook_publish} onClick={() => setConfirm("publish")}><Send size={15} />发布不可变快照</Button></> : <Button disabled={!canEdit || !name || !newCode} onClick={() => create.mutate()}><Plus size={15} />创建 Trigger 与服务账号</Button>}</Card>{trigger ? <Card><div className="section-heading"><div><h2>接入信息</h2><p>public ID 可轮换但不是认证凭证。</p></div></div><code className="endpoint-code">/webhooks/v1/{trigger.definition.public_id}</code>{user?.capabilities.webhook_rotate ? <Button variant="danger" onClick={() => setConfirm("rotate")}><RotateCcw size={15} />轮换 public ID</Button> : null}</Card> : null}{trigger ? <PublicationHistory trigger={trigger} canPublish={Boolean(user?.capabilities.webhook_publish)} onRollback={(id) => rollback.mutate(id)} /> : null}</aside>
    </div>
    {confirm ? <ConfirmDialog kind={confirm} onCancel={() => setConfirm(null)} onConfirm={() => { if (confirm === "publish" && revision) publish.mutate(revision.id); if (confirm === "rotate") rotate.mutate(); setConfirm(null); }} /> : null}
  </>;
}

function TriggerStatus({ trigger, onEnable, onServiceAccount, canEdit, canManageService }: { trigger: WebhookTriggerPayload; onEnable: (enabled: boolean) => void; onServiceAccount: (enabled: boolean) => void; canEdit: boolean; canManageService: boolean }) {
  const definition = trigger.definition;
  return <div className="agent-status-strip"><div><span>Trigger 状态</span><strong>{definition.status}</strong></div><div><span>当前 publication</span><strong>r{trigger.current_publication?.revision ?? "—"}</strong></div><div><span>服务账号</span><code>{definition.service_account_username}</code></div><div className="status-actions">{canEdit ? <Button variant="ghost" onClick={() => onEnable(definition.status !== "enabled")}>{definition.status === "enabled" ? "停用 Trigger" : "启用 Trigger"}</Button> : null}{canManageService ? <Button variant="ghost" onClick={() => onServiceAccount(definition.service_account_status !== "enabled")}>{definition.service_account_status === "enabled" ? "停用服务账号" : "启用服务账号"}</Button> : null}</div></div>;
}

function AdvancedJsonField({ label, value, onChange, disabled }: { label: string; value: unknown; onChange: (value: string) => void; disabled: boolean }) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  return <Field label={label}><textarea className="input advanced-json" value={text} disabled={disabled} onChange={(event) => setText(event.target.value)} onBlur={() => onChange(text)} /></Field>;
}

function PublicationHistory({ trigger, canPublish, onRollback }: { trigger: WebhookTriggerPayload; canPublish: boolean; onRollback: (id: string) => void }) {
  return <Card><div className="section-heading"><div><h2>发布历史</h2><p>回滚只移动当前指针。</p></div><FileClock size={18} /></div><div className="publication-list">{trigger.publications.map((item) => <div className={`publication-item ${item.id === trigger.current_publication?.id ? "current" : ""}`} key={item.id}><div><strong>revision {item.revision}</strong><span>{formatTime(item.published_at)}</span><code>{item.config_hash.slice(0, 12)}</code></div>{item.id === trigger.current_publication?.id ? <Badge tone="good">current</Badge> : canPublish ? <Button variant="ghost" onClick={() => onRollback(item.id)}><RotateCcw size={14} />回滚</Button> : null}</div>)}</div></Card>;
}

function ConfirmDialog({ kind, onCancel, onConfirm }: { kind: "publish" | "rotate"; onCancel: () => void; onConfirm: () => void }) {
  return <div className="dialog-backdrop"><div className="confirm-dialog" role="dialog" aria-modal="true"><span className="eyebrow">Explicit confirmation</span><h2>{kind === "publish" ? "发布 Trigger 快照" : "轮换公共入口 ID"}</h2><p>{kind === "publish" ? "新事件会固定使用此 Trigger 与 Agent publication；已接收事件不受后续草稿影响。" : "旧 URL 会立即失效，必须同步更新来源系统。认证 secret 不会因此改变。"}</p><div className="dialog-actions"><Button variant="ghost" onClick={onCancel}>取消</Button><Button variant={kind === "rotate" ? "danger" : "primary"} onClick={onConfirm}>确认</Button></div></div></div>;
}

export function WebhookEventsPage() {
  const { code = "" } = useParams();
  const [status, setStatus] = useState("");
  const query = useQuery({ queryKey: ["webhook-events", code, status], queryFn: () => api<{ events: WebhookEvent[] }>(`/api/admin/webhook-triggers/${code}/events${status ? `?status=${encodeURIComponent(status)}` : ""}`) });
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useQuery({ queryKey: ["webhook-event", selected], queryFn: () => api<{ event: WebhookEvent; evidence: Record<string, unknown> }>(`/api/admin/webhook-events/${selected}`), enabled: Boolean(selected) });
  return <><PageHeader eyebrow="Webhook evidence" title={`${code} 事件记录`} description="展示认证、过滤、Outbox、job、工具和投递状态；不展示原始 payload、secret 或完整报告。" actions={<Link className="button button-ghost" to={`/admin/webhooks/${code}`}><ArrowLeft size={15} />返回 Trigger</Link>} /><ErrorNotice error={query.error || detail.error} /><div className="master-detail"><Card className="master-list"><Field label="状态筛选"><select className="input" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部</option>{["REJECTED_AUTH", "REJECTED", "IGNORED", "ACCEPTED", "DISPATCH_PENDING", "JOB_CREATED", "DISPATCH_FAILED"].map((value) => <option key={value}>{value}</option>)}</select></Field><div className="event-list">{query.data?.events.map((event) => <button className={`event-button ${selected === event.id ? "selected" : ""}`} key={event.id} onClick={() => setSelected(event.id)}><span>{formatTime(event.received_at)}</span><strong>{event.external_event_id || event.error_code || event.id}</strong><Badge tone={event.status === "JOB_CREATED" ? "good" : event.status.startsWith("REJECTED") || event.status.endsWith("FAILED") ? "bad" : event.status === "IGNORED" ? "neutral" : "warn"}>{event.status}</Badge></button>)}</div></Card><Card>{detail.data ? <><div className="section-heading"><div><h2>事件状态链</h2><p>{detail.data.event.correlation_id}</p></div></div><pre className="config-preview event-detail-preview">{JSON.stringify(detail.data, null, 2)}</pre></> : <EmptyState title="选择一条事件" message="查看固定 Trigger/Agent publication、job、工具调用和投递安全摘要。" />}</Card></div></>;
}

function defaultConfig(catalog: Catalog): WebhookTriggerConfig {
  const fixed = (value = "") => ({ mode: "fixed" as const, value, pointer: "", allowed_values: [] as string[] });
  const delivery = catalog.connectors.find((item) => Boolean(item.allow_delivery));
  return {
    schema_version: 1,
    adapter: "grafana_alertmanager_v1",
    authentication: { type: "bearer_v1", secret_ref: "env:GRAFANA_WEBHOOK_TOKEN", timestamp_header: "x-webhook-timestamp", nonce_header: "x-webhook-nonce", signature_header: "x-webhook-signature", window_seconds: 300 },
    mapping: { variables: { summary: "/commonAnnotations/summary" }, filters: [], message_template: "Diagnose this firing alert: {summary}", event_id_pointer: "/event_id", status_pointer: "/status" },
    routing: { project_code: fixed("default"), environment: fixed("prod"), base: fixed(), workshop: fixed(), service: fixed() },
    agent: { code: catalog.agent.code, publication_id: catalog.agent.publication_id },
    delivery: { type: "dingtalk_webhook_robot", connector_id: delivery?.id ?? "", target: { webhook_id: "grafana-alert" }, options: {} },
    idempotency: { cooldown_seconds: 300 },
    limits: { requests_per_minute: 60, max_in_flight: 10, max_alerts: 20 },
  };
}
