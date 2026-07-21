import { useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@enterprise-agent/ui/components/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@enterprise-agent/ui/components/dialog";
import { Input } from "@enterprise-agent/ui/components/input";
import { Label } from "@enterprise-agent/ui/components/label";
import type { ChannelProvider, Connector, ConnectorDraft, ToolProvider, ToolResource, ToolResourceDraft } from "../domain/models";
import { useManagedSecrets } from "../application/queries";

type ToolFormProps = {
  open: boolean;
  providers: ToolProvider[];
  resource: ToolResource | null;
  pending: boolean;
  error: unknown;
  onOpenChange: (open: boolean) => void;
  onSubmit: (draft: ToolResourceDraft) => void;
};

const emptyTool = (): ToolResourceDraft => ({
  expected_revision: 0, code: "", scope_type: "environment", environment_code: "local",
  base_code: "", workshop_code: "", resource_kind: "database", engine: "postgresql",
  config: { host: "", port: 5432, database: "", username: "", host_allowlist: [] },
  secret_refs: { password: "" }, status: "enabled",
});

export function ToolResourceForm({ open, providers, resource, pending, error, onOpenChange, onSubmit }: ToolFormProps) {
  const [draft, setDraft] = useState<ToolResourceDraft>(() => resource ? { ...resource, expected_revision: resource.revision } : emptyTool());
  const provider = providers.find((item) => item.code === draft.resource_kind);
  const config = draft.config;
  const update = (key: string, value: unknown) => setDraft((current) => ({ ...current, config: { ...current.config, [key]: value } }));
  const changeKind = (kind: ToolResourceDraft["resource_kind"]) => {
    const next = kind === "loki"
      ? { base_url: "https://", tenant_id: "", host_allowlist: [] }
      : kind === "redis"
        ? { host: "", port: 6379, database: 0, username: "", tls: false, host_allowlist: [] }
        : { host: "", port: 5432, database: "", username: "", schema: "", host_allowlist: [] };
    setDraft((current) => ({ ...current, resource_kind: kind, engine: kind === "database" ? "postgresql" : "", config: next, secret_refs: { [kind === "loki" ? "token" : "password"]: "" } }));
  };
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"><form onSubmit={(event: FormEvent) => { event.preventDefault(); onSubmit(draft); }} className="space-y-5">
    <DialogHeader><DialogTitle>{resource ? "编辑工具资源" : "新建工具资源"}</DialogTitle><DialogDescription>只允许 Provider Registry 中的只读资源。目标主机必须显式加入 allowlist。</DialogDescription></DialogHeader>
    <FormError error={error}/>
    <div className="form-two"><FormField label="资源 code"><Input required minLength={2} disabled={Boolean(resource)} value={draft.code} onChange={(e)=>setDraft({...draft,code:e.target.value})}/></FormField><FormField label="Provider"><select className="input" value={draft.resource_kind} onChange={(e)=>changeKind(e.target.value as ToolResourceDraft["resource_kind"])} disabled={Boolean(resource)}>{providers.filter(p=>p.available).map(p=><option key={p.code} value={p.code}>{p.name}</option>)}</select></FormField></div>
    <div className="form-three"><FormField label="范围"><select className="input" value={draft.scope_type} onChange={(e)=>setDraft({...draft,scope_type:e.target.value as ToolResourceDraft["scope_type"]})}><option value="environment">环境</option><option value="base">基地</option><option value="workshop">车间</option></select></FormField><FormField label="环境"><Input required value={draft.environment_code} onChange={(e)=>setDraft({...draft,environment_code:e.target.value})}/></FormField>{draft.scope_type !== "environment" ? <FormField label="基地"><Input required value={draft.base_code} onChange={(e)=>setDraft({...draft,base_code:e.target.value})}/></FormField> : null}{draft.scope_type === "workshop" ? <FormField label="车间"><Input required value={draft.workshop_code} onChange={(e)=>setDraft({...draft,workshop_code:e.target.value})}/></FormField> : null}</div>
    {draft.resource_kind === "database" ? <><FormField label="数据库类型"><select className="input" value={draft.engine} onChange={(e)=>setDraft({...draft,engine:e.target.value})}>{provider?.dialects.map(d=><option key={d} value={d}>{d}</option>)}</select></FormField><div className="form-two"><FormField label="主机"><Input required value={String(config.host??"")} onChange={(e)=>update("host",e.target.value)}/></FormField><FormField label="端口"><Input required type="number" value={Number(config.port??0)} onChange={(e)=>update("port",Number(e.target.value))}/></FormField><FormField label="数据库"><Input required value={String(config.database??"")} onChange={(e)=>update("database",e.target.value)}/></FormField><FormField label="只读用户名"><Input required value={String(config.username??"")} onChange={(e)=>update("username",e.target.value)}/></FormField></div></> : null}
    {draft.resource_kind === "redis" ? <div className="form-two"><FormField label="主机"><Input required value={String(config.host??"")} onChange={(e)=>update("host",e.target.value)}/></FormField><FormField label="端口"><Input required type="number" value={Number(config.port??6379)} onChange={(e)=>update("port",Number(e.target.value))}/></FormField><FormField label="Database"><Input type="number" value={Number(config.database??0)} onChange={(e)=>update("database",Number(e.target.value))}/></FormField><FormField label="用户名"><Input value={String(config.username??"")} onChange={(e)=>update("username",e.target.value)}/></FormField></div> : null}
    {draft.resource_kind === "loki" ? <div className="form-two"><FormField label="HTTPS Base URL"><Input required type="url" value={String(config.base_url??"")} onChange={(e)=>update("base_url",e.target.value)}/></FormField><FormField label="Tenant ID"><Input value={String(config.tenant_id??"")} onChange={(e)=>update("tenant_id",e.target.value)}/></FormField></div> : null}
    <div className="form-two"><FormField label="Host allowlist" hint="多个主机用逗号分隔，必须包含上面的目标主机。"><Input required value={(config.host_allowlist as string[] ?? []).join(", ")} onChange={(e)=>update("host_allowlist",e.target.value.split(",").map(v=>v.trim()).filter(Boolean))}/></FormField><SecretSelector label={`${draft.resource_kind === "loki" ? "Token" : "Password"} Secret`} value={String(Object.values(draft.secret_refs)[0]??"")} onChange={(value)=>setDraft({...draft,secret_refs:{[draft.resource_kind === "loki"?"token":"password"]:value}})}/></div>
    <DialogFooter><Button type="button" variant="outline" onClick={()=>onOpenChange(false)}>取消</Button><Button type="submit" disabled={pending}>{pending?"保存中…":"保存资源"}</Button></DialogFooter>
  </form></DialogContent></Dialog>;
}

type ChannelFormProps = { open:boolean; providers:ChannelProvider[]; connector:Connector|null; pending:boolean; error:unknown; onOpenChange:(open:boolean)=>void; onValidate:(draft:ConnectorDraft)=>void; onSubmit:(draft:ConnectorDraft)=>void };
const emptyConnector = ():ConnectorDraft => ({ expected_revision:0,id:"",connector_type:"dingtalk_enterprise_stream",name:"",base_url:"",enabled:true,allow_ingress:true,allow_delivery:false,secret_ref:"",endpoint_ref:"",host_allowlist:[],metadata:{} });

export function ChannelConnectorForm({open,providers,connector,pending,error,onOpenChange,onValidate,onSubmit}:ChannelFormProps){
  const [draft,setDraft]=useState<ConnectorDraft>(()=>connector?{...connector,expected_revision:connector.revision}:emptyConnector());
  const provider=providers.find(p=>p.code===draft.connector_type);
  const changeProvider=(code:string)=>{const next=providers.find(p=>p.code===code);setDraft(current=>({...current,connector_type:code,allow_ingress:next?.directions.includes("ingress")??false,allow_delivery:next?.directions.includes("delivery")??false}));};
  const metadata=draft.metadata??{};
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"><form onSubmit={(event)=>{event.preventDefault();onSubmit(draft);}} className="space-y-5"><DialogHeader><DialogTitle>{connector?"编辑 Channel Connector":"新建 Channel Connector"}</DialogTitle><DialogDescription>入口与投递方向由 Provider 限定；“校验”只检查配置，不会发送消息。</DialogDescription></DialogHeader><FormError error={error}/>
    <div className="form-two"><FormField label="名称"><Input required minLength={2} value={draft.name} onChange={e=>setDraft({...draft,name:e.target.value})}/></FormField><FormField label="Provider"><select className="input" value={draft.connector_type} disabled={Boolean(connector)} onChange={e=>changeProvider(e.target.value)}>{providers.map(p=><option key={p.code} value={p.code} disabled={!p.available}>{p.name}{p.available?"":"（未开放）"}</option>)}</select></FormField></div>
    <div className="form-two"><SecretSelector label="Connector Secret" value={draft.secret_ref} onChange={(value)=>setDraft({...draft,secret_ref:value})}/><SecretSelector label="Endpoint Secret" value={draft.endpoint_ref??""} onChange={(value)=>setDraft({...draft,endpoint_ref:value})}/><FormField label="HTTPS Base URL"><Input type="url" value={draft.base_url??""} onChange={e=>setDraft({...draft,base_url:e.target.value})}/></FormField><FormField label="Host allowlist"><Input value={draft.host_allowlist.join(", ")} onChange={e=>setDraft({...draft,host_allowlist:e.target.value.split(",").map(v=>v.trim()).filter(Boolean)})}/></FormField></div>
    {provider?.required.includes("metadata.client_id_ref")?<div className="form-two"><FormField label="Client ID 引用"><Input value={String(metadata.client_id_ref??"")} onChange={e=>setDraft({...draft,metadata:{...metadata,client_id_ref:e.target.value}})}/></FormField>{provider.required.includes("metadata.tenant_code")?<FormField label="租户 code"><Input value={String(metadata.tenant_code??"")} onChange={e=>setDraft({...draft,metadata:{...metadata,tenant_code:e.target.value}})}/></FormField>:null}</div>:null}
    <div className="rounded-lg border bg-muted/30 p-3 text-sm"><strong>方向：</strong>{draft.allow_ingress?"Ingress":""}{draft.allow_ingress&&draft.allow_delivery?" + ":""}{draft.allow_delivery?"Delivery":""}</div>
    <DialogFooter><Button type="button" variant="outline" onClick={()=>onOpenChange(false)}>取消</Button><Button type="button" variant="secondary" disabled={pending} onClick={()=>onValidate(draft)}>只校验配置</Button><Button type="submit" disabled={pending}>{pending?"保存中…":"保存 Connector"}</Button></DialogFooter>
  </form></DialogContent></Dialog>;
}

function FormField({label,hint,children}:{label:string;hint?:string;children:ReactNode}){return <div className="space-y-2"><Label>{label}</Label>{children}{hint?<p className="text-xs text-muted-foreground">{hint}</p>:null}</div>}
function FormError({error}:{error:unknown}){if(!error)return null;const value=error as {code?:string;message?:string;correlationId?:string;fieldErrors?:Array<{field?:string;message?:string}>};return <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><strong className="block">{value.code==="revision_conflict"?"资源已被其他人修改":"无法保存"}</strong><span>{value.message}{value.correlationId?` · correlation ${value.correlationId}`:""}</span>{value.fieldErrors?.map((item,index)=><span className="block" key={index}>{item.field}: {item.message}</span>)}</div>}

function SecretSelector({label,value,onChange}:{label:string;value:string;onChange:(value:string)=>void}){
  const {query,create}=useManagedSecrets();
  const [creating,setCreating]=useState(false);
  const [draft,setDraft]=useState({code:"",value:"",purpose:""});
  const submit=()=>{const payload={...draft};setDraft(current=>({...current,value:""}));create.mutate(payload,{onSuccess:({secret})=>{onChange(secret.secret_ref);setDraft({code:"",value:"",purpose:""});setCreating(false);}});};
  return <FormField label={label} hint="可选择受控引用，或输入 env:/secret:// /vault:/kms: 引用。明文仅在创建请求中出现。"><div className="space-y-2"><select className="input" aria-label={`${label} 已有引用`} value={query.data?.secrets.some(item=>item.secret_ref===value)?value:""} onChange={event=>onChange(event.target.value)}><option value="">选择已有 Secret</option>{query.data?.secrets.map(item=><option key={item.id} value={item.secret_ref}>{item.code} · {item.masked_summary}</option>)}</select><Input aria-label={`${label} 引用`} value={value} onChange={event=>onChange(event.target.value)} placeholder="secret://resource/credential"/><Button type="button" size="sm" variant="outline" onClick={()=>setCreating(current=>!current)}>{creating?"取消创建":"新建受控 Secret"}</Button>{creating?<div className="rounded-lg border bg-muted/30 p-3 space-y-2"><Input aria-label="Secret code" value={draft.code} onChange={event=>setDraft({...draft,code:event.target.value})} placeholder="resource_password"/><Input aria-label="Secret 用途" value={draft.purpose} onChange={event=>setDraft({...draft,purpose:event.target.value})} placeholder="用途说明"/><Input aria-label="Secret 明文" type="password" autoComplete="new-password" value={draft.value} onChange={event=>setDraft({...draft,value:event.target.value})} placeholder="只写入，不回显"/><Button type="button" size="sm" disabled={create.isPending||!draft.code||!draft.value} onClick={submit}>{create.isPending?"写入中…":"创建并选择"}</Button><FormError error={create.error}/></div>:null}</div></FormField>;
}
