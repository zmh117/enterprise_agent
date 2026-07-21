import { useState } from "react";
import { Cable, CheckCircle2, Database, FileCode2, Plus, ServerCog } from "lucide-react";
import { toast } from "@enterprise-agent/ui/components/sonner";
import { Badge } from "@enterprise-agent/ui/components/badge";
import { Button } from "@enterprise-agent/ui/components/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@enterprise-agent/ui/components/card";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@enterprise-agent/ui/components/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@enterprise-agent/ui/components/table";
import { useAuth } from "../../../app/providers/auth-provider";
import { useChannelCatalog, useChannelCommands, useSkillCatalog, useToolCatalog, useToolCommands } from "../application/queries";
import type { Connector, ConnectorDraft, ToolResource, ToolResourceDraft } from "../domain/models";
import { PageHeading } from "../../operations/presentation/pages";
import { ChannelConnectorForm, ToolResourceForm } from "./forms";

export function SkillsPage() {
  const query = useSkillCatalog();
  const items = query.data?.skills ?? [];
  return <div className="space-y-6">
    <PageHeading eyebrow="Managed filesystem" title="Skill Catalog" description="展示服务端受控加载结果，并可分配给默认诊断 Agent；Web 不上传、编辑或删除 Skill 文件。"/>
    {query.isError ? <State title="Skill Catalog 暂不可用" detail="加载错误已经脱敏，请稍后重试。"/> : null}
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{items.map(item=><Card key={item.code}><CardHeader><div className="flex items-center justify-between"><span className="metric-icon"><FileCode2 size={17}/></span><Badge variant={item.assignable?"secondary":"destructive"}>{item.status}</Badge></div><CardTitle className="text-base">{item.name}</CardTitle><CardDescription className="font-mono">{item.code}</CardDescription></CardHeader><CardContent><p className="text-sm text-muted-foreground">{item.description||item.error_summary||"暂无描述"}</p><div className="mt-4 text-xs text-muted-foreground">来源 · {item.source}</div></CardContent></Card>)}</div>
    {!query.isLoading&&!query.isError&&!items.length?<State title="暂无可用 Skill" detail="服务端受控目录中还没有可加载的 Skill。"/>:null}
  </div>;
}

export function ToolsPage() {
  const { can } = useAuth();
  const { providers, resources } = useToolCatalog();
  const commands = useToolCommands();
  const supported = providers.data?.providers ?? [];
  const items = resources.data?.items ?? [];
  const [selected, setSelected] = useState<ToolResource | null>(null);
  const [editing, setEditing] = useState<ToolResource | null | undefined>(undefined);
  const save = (draft: ToolResourceDraft) => commands.save.mutate(draft, { onSuccess: ({resource}) => { setEditing(undefined); setSelected(resource); toast.success("工具资源已保存"); } });
  return <div className="space-y-6">
    <PageHeading eyebrow="Typed read-only resources" title="API 工具" description="管理 database、Redis、Loki 资源与 Secret 引用；连接测试必须显式触发并只执行最小只读探测。"/>
    <div className="grid gap-3 md:grid-cols-3">{supported.map(item=><Card key={item.code}><CardHeader className="pb-3"><div className="flex items-center justify-between"><CardTitle className="flex items-center gap-2 text-base"><Database size={16}/>{item.name}</CardTitle><Badge variant="secondary">available</Badge></div><CardDescription>{item.dialects.join(" · ")||item.probe}</CardDescription></CardHeader></Card>)}</div>
    <Card><CardHeader className="flex-row items-center justify-between"><div><CardTitle>资源实例</CardTitle><CardDescription>Secret 只显示受控引用；Oracle 未进入当前 runtime registry。</CardDescription></div>{can("tools.manage")?<Button onClick={()=>setEditing(null)}><Plus/>新建资源</Button>:null}</CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>资源</TableHead><TableHead>类型</TableHead><TableHead>范围</TableHead><TableHead>状态</TableHead><TableHead>Revision</TableHead></TableRow></TableHeader><TableBody>{items.map(item=><TableRow key={item.id} className="cursor-pointer" onClick={()=>setSelected(item)}><TableCell className="font-medium">{item.code}</TableCell><TableCell>{item.resource_kind}{item.engine?` · ${item.engine}`:""}</TableCell><TableCell>{[item.environment_code,item.base_code,item.workshop_code].filter(Boolean).join(" / ")}</TableCell><TableCell><Badge variant="outline">{item.status}</Badge></TableCell><TableCell>{item.revision}</TableCell></TableRow>)}</TableBody></Table>{!resources.isLoading&&!items.length?<State title="暂无工具资源" detail="创建受控的 database、Redis 或 Loki 只读连接。"/>:null}</CardContent></Card>
    {editing!==undefined?<ToolResourceForm key={editing?.id??"new"} open resource={editing??null} providers={supported} pending={commands.save.isPending} error={commands.save.error} onOpenChange={(open)=>{if(!open){setEditing(undefined);commands.save.reset();}}} onSubmit={save}/>:null}
    <Sheet open={Boolean(selected)} onOpenChange={(open)=>{if(!open)setSelected(null);}}><SheetContent className="sm:max-w-xl"><SheetHeader><SheetTitle>{selected?.code}</SheetTitle><SheetDescription>受控资源详情；凭据永不回显。</SheetDescription></SheetHeader>{selected?<div className="space-y-5 p-4"><Detail label="Provider" value={`${selected.resource_kind}${selected.engine?` · ${selected.engine}`:""}`}/><Detail label="Scope" value={[selected.environment_code,selected.base_code,selected.workshop_code].filter(Boolean).join(" / ")}/><Detail label="Revision" value={String(selected.revision)}/><Detail label="Secret refs" value={Object.values(selected.secret_refs).join(", ")||"无"}/><pre className="safe-json">{JSON.stringify(selected.config,null,2)}</pre><div className="flex flex-wrap gap-2">{can("tools.manage")?<><Button variant="outline" onClick={()=>{setEditing(selected);setSelected(null);}}>编辑</Button><Button variant="outline" disabled={commands.status.isPending} onClick={()=>commands.status.mutate(selected,{onSuccess:({resource})=>{setSelected(resource);toast.success(resource.status==="enabled"?"资源已启用":"资源已停用");}})}>{selected.status==="enabled"?"停用":"启用"}</Button></>:null}{can("tools.test")?<Button disabled={commands.test.isPending} onClick={()=>commands.test.mutate(selected.code,{onSuccess:({result})=>toast.success(`${result.summary} · ${result.duration_ms??0}ms · ${result.correlation_id}`),onError:(error)=>toast.error(error instanceof Error?error.message:"连接测试失败")})}>{commands.test.isPending?"测试中…":"显式连接测试"}</Button>:null}</div></div>:null}</SheetContent></Sheet>
  </div>;
}

export function ChannelsPage() {
  const { can } = useAuth();
  const { providers, connectors } = useChannelCatalog();
  const commands = useChannelCommands();
  const allProviders = providers.data?.providers ?? [];
  const items = connectors.data?.items ?? [];
  const [selected,setSelected]=useState<Connector|null>(null);
  const [editing,setEditing]=useState<Connector|null|undefined>(undefined);
  const save=(draft:ConnectorDraft)=>commands.save.mutate(draft,{onSuccess:({connector})=>{setEditing(undefined);setSelected(connector);toast.success("Connector 已保存");}});
  const validate=(draft:ConnectorDraft)=>commands.validate.mutate(draft,{onSuccess:({result})=>toast.success(`${result.summary} · ${result.correlation_id}`),onError:(error)=>toast.error(error instanceof Error?error.message:"配置校验失败")});
  return <div className="space-y-6">
    <PageHeading eyebrow="Ingress & delivery" title="Channel" description="入口和结果投递分别建模。MVP 只开放已经实现的钉钉 Stream、Callback 与 Delivery Provider。"/>
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{allProviders.map(item=><Card key={item.code} className={!item.available?"opacity-55":""}><CardHeader><div className="flex items-center justify-between"><span className="metric-icon"><Cable size={17}/></span><Badge variant={item.available?"secondary":"outline"}>{item.available?"available":"unavailable"}</Badge></div><CardTitle className="text-base">{item.name}</CardTitle><CardDescription>{item.directions.join(" + ")}</CardDescription></CardHeader></Card>)}</div>
    <Card><CardHeader className="flex-row items-center justify-between"><div><CardTitle>Connector</CardTitle><CardDescription>配置校验不会发送真实消息。</CardDescription></div>{can("channels.manage")?<Button onClick={()=>setEditing(null)}><Plus/>新建 Connector</Button>:null}</CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>名称</TableHead><TableHead>Provider</TableHead><TableHead>方向</TableHead><TableHead>状态</TableHead><TableHead>Revision</TableHead></TableRow></TableHeader><TableBody>{items.map(item=><TableRow key={item.id} className="cursor-pointer" onClick={()=>setSelected(item)}><TableCell className="font-medium">{item.name}</TableCell><TableCell>{item.connector_type}</TableCell><TableCell>{item.allow_ingress?"Ingress":""}{item.allow_ingress&&item.allow_delivery?" + ":""}{item.allow_delivery?"Delivery":""}</TableCell><TableCell><Badge variant={item.enabled?"secondary":"outline"}>{item.enabled?"enabled":"disabled"}</Badge></TableCell><TableCell>{item.revision}</TableCell></TableRow>)}</TableBody></Table>{!connectors.isLoading&&!items.length?<State title="暂无 Connector" detail="创建一个已经开放的钉钉入口或结果投递连接。"/>:null}</CardContent></Card>
    <div className="safety-callout"><CheckCircle2/><div><strong>安全边界</strong><p>不接受任意 HTTP、脚本、Shell 或写工具定义；邮件与企业微信仍为 unavailable。</p></div><ServerCog/></div>
    {editing!==undefined?<ChannelConnectorForm key={editing?.id??"new"} open connector={editing??null} providers={allProviders} pending={commands.save.isPending||commands.validate.isPending} error={commands.save.error||commands.validate.error} onOpenChange={(open)=>{if(!open){setEditing(undefined);commands.save.reset();commands.validate.reset();}}} onSubmit={save} onValidate={validate}/>:null}
    <Sheet open={Boolean(selected)} onOpenChange={(open)=>{if(!open)setSelected(null);}}><SheetContent className="sm:max-w-xl"><SheetHeader><SheetTitle>{selected?.name}</SheetTitle><SheetDescription>Connector 配置与受控方向。</SheetDescription></SheetHeader>{selected?<div className="space-y-5 p-4"><Detail label="Provider" value={selected.connector_type}/><Detail label="方向" value={`${selected.allow_ingress?"Ingress":""}${selected.allow_ingress&&selected.allow_delivery?" + ":""}${selected.allow_delivery?"Delivery":""}`}/><Detail label="Secret ref" value={selected.secret_ref||"无"}/><Detail label="Host allowlist" value={selected.host_allowlist.join(", ")||"无"}/>{can("channels.manage")?<div className="flex gap-2"><Button variant="outline" onClick={()=>{setEditing(selected);setSelected(null);}}>编辑</Button><Button variant="outline" disabled={commands.status.isPending} onClick={()=>commands.status.mutate(selected,{onSuccess:({connector})=>{setSelected(connector);toast.success(connector.enabled?"Connector 已启用":"Connector 已停用");}})}>{selected.enabled?"停用":"启用"}</Button></div>:null}</div>:null}</SheetContent></Sheet>
  </div>;
}

function Detail({label,value}:{label:string;value:string}){return <div><span className="text-xs text-muted-foreground">{label}</span><p className="mt-1 break-all text-sm font-medium text-foreground">{value||"—"}</p></div>}
function State({title,detail}:{title:string;detail:string}){return <div className="empty-panel"><strong>{title}</strong><p>{detail}</p></div>}
