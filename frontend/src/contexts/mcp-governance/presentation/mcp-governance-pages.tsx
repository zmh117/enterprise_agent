import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  DatabaseIcon,
  KeyRoundIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  RotateCwIcon,
  ServerIcon,
  ShieldCheckIcon,
  SquareIcon,
  WrenchIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  createCredential,
  createMcpTool,
  disableCredential,
  getResourceForm,
  listCredentials,
  listMcpCatalog,
  listMcpResources,
  listMcpServers,
  listMcpTools,
  listResourceCredentialCandidates,
  rotateCredential,
  saveResourceForm,
  transitionMcpResource,
  transitionMcpTool,
  type CredentialSummary,
  type ResourceForm,
  type ResourceKind,
} from "@/contexts/mcp-governance/infrastructure/mcp-governance-api"
import { useAuthenticatedUser } from "@/contexts/auth/presentation/authenticated-user-state"
import {
  ManagementError,
  ManagementLoading,
  ManagementPage,
  MutationNotice,
} from "@/shared/presentation/management-states"
import { SectionHeading } from "@/shared/presentation/section-heading"

const keys = {
  servers: ["admin", "mcp", "servers"] as const,
  tools: ["admin", "mcp", "tools"] as const,
  catalog: ["admin", "mcp", "catalog"] as const,
  resources: ["admin", "mcp", "resources"] as const,
  credentials: ["admin", "mcp", "credentials"] as const,
}

export function McpServersPage() {
  const query = useQuery({ queryKey: keys.servers, queryFn: listMcpServers })
  return (
    <ManagementPage>
      <SectionHeading
        eyebrow="MCP Governance"
        title="受信 MCP Server"
        description="Server 来自代码和部署配置，只能查看与执行固定健康检查；这里不接受 URL、Transport、Header 或认证配置。"
        action={<RefreshButton query={query} />}
      />
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error} retry={() => void query.refetch()} />
      <div className="grid gap-4 lg:grid-cols-2">
        {query.data?.map((server) => (
          <Card key={server.server_code} className="shadow-none">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="flex items-center gap-2">
                  <ServerIcon className="size-4" />
                  {server.server_code}
                </CardTitle>
                <StatusBadge value={server.health.status || "unavailable"} />
              </div>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
              <Summary label="Server Version" value={server.health.server_version || "未报告"} />
              <Summary label="来源" value={server.source} />
              <Summary label="Transport" value={`${server.transport.type} · ${server.transport.authentication}`} />
              <Summary label="活动 Tool Publication" value={String(server.active_publications)} />
              <Summary label="Generation" value={server.health.generation_status || "不适用"} />
              <Summary
                label="活动 Generation"
                value={String(server.health.active_generation_count ?? 0)}
              />
            </CardContent>
          </Card>
        ))}
      </div>
    </ManagementPage>
  )
}

export function McpToolsPage() {
  const user = useAuthenticatedUser()
  const query = useQuery({ queryKey: keys.tools, queryFn: listMcpTools })
  const catalog = useQuery({ queryKey: keys.catalog, queryFn: listMcpCatalog })
  const resources = useQuery({ queryKey: keys.resources, queryFn: listMcpResources })
  const client = useQueryClient()
  const [creating, setCreating] = useState(false)
  const mutation = useMutation({
    mutationFn: (input: { code: string; action: "verify" | "publish" | "disable"; revision: number }) =>
      transitionMcpTool(input.code, input.action, input.revision),
    onSuccess: async () => client.invalidateQueries({ queryKey: keys.tools }),
  })
  return (
    <ManagementPage>
      <SectionHeading
        eyebrow="MCP Governance"
        title="Tool Publication"
        description="只能从服务端发现目录选择 Tool；浏览器不能提交 Tool Schema、Server 归属或可执行实现。"
        action={
          <div className="flex gap-2">
            <RefreshButton query={query} />
            {query.data?.permissions.can_create && user.capabilities.mcp_tools_manage ? (
              <Button type="button" onClick={() => setCreating((value) => !value)}>
                <PlusIcon />新建发布项
              </Button>
            ) : null}
          </div>
        }
      />
      {creating ? (
        <CreateToolForm
          catalog={catalog.data ?? []}
          resources={resources.data ?? []}
          onCreated={async () => {
            setCreating(false)
            await client.invalidateQueries({ queryKey: keys.tools })
          }}
        />
      ) : null}
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error || catalog.error || resources.error} retry={() => void query.refetch()} />
      <MutationNotice error={mutation.error} />
      <div className="space-y-3">
        {query.data?.tools.map((tool) => (
          <Card key={tool.code} className="shadow-none">
            <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <WrenchIcon className="size-4" />
                  <p className="font-medium">{tool.name}</p>
                  <StatusBadge value={tool.lifecycle_status} />
                  {tool.draft ? <StatusBadge value={tool.draft.status} /> : null}
                </div>
                <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                  {tool.code} · {tool.catalog_key} · r{tool.revision}
                </p>
              </div>
              {user.capabilities.mcp_tools_manage ? (
                <div className="flex flex-wrap gap-2">
                  {tool.draft?.status === "DRAFT" ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={mutation.isPending}
                      onClick={() => mutation.mutate({ code: tool.code, action: "verify", revision: tool.revision })}
                    >
                      <ShieldCheckIcon />校验
                    </Button>
                  ) : null}
                  {tool.draft?.status === "VERIFIED" ? (
                    <Button
                      type="button"
                      disabled={mutation.isPending}
                      onClick={() => mutation.mutate({ code: tool.code, action: "publish", revision: tool.revision })}
                    >
                      发布
                    </Button>
                  ) : null}
                  {tool.publications.some((item) => item.status === "PUBLISHED") ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={mutation.isPending}
                      onClick={() => mutation.mutate({ code: tool.code, action: "disable", revision: tool.revision })}
                    >
                      <SquareIcon />停用
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>
    </ManagementPage>
  )
}

function CreateToolForm({
  catalog,
  resources,
  onCreated,
}: {
  catalog: Awaited<ReturnType<typeof listMcpCatalog>>
  resources: Awaited<ReturnType<typeof listMcpResources>>
  onCreated: () => Promise<void>
}) {
  const [catalogKey, setCatalogKey] = useState("")
  const mutation = useMutation({ mutationFn: createMcpTool, onSuccess: onCreated })
  const selected = catalog.find((entry) => entry.catalog_key === catalogKey)
  const eligible = selected?.resource_kind
    ? resources.filter(
        (item) =>
          item.resource.kind === selected.resource_kind &&
          item.deployment?.status === "ACTIVE" &&
          item.deployment.id
      )
    : []
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    mutation.mutate({
      code: String(data.get("code") || ""),
      name: String(data.get("name") || ""),
      catalog_key: String(data.get("catalog_key") || ""),
      resource_deployment_id: String(data.get("resource_deployment_id") || ""),
    })
  }
  return (
    <Card className="shadow-none">
      <CardHeader><CardTitle>新建 Tool Publication</CardTitle></CardHeader>
      <CardContent>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
          <TextField name="code" label="稳定代码" required />
          <TextField name="name" label="显示名称" required />
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="tool-catalog-key">受信 Tool</Label>
            <select id="tool-catalog-key" name="catalog_key" required value={catalogKey} onChange={(event) => setCatalogKey(event.target.value)} className="h-9 w-full rounded-md border bg-background px-3 text-sm">
              <option value="">请选择服务端目录项</option>
              {catalog.map((entry) => (
                <option key={entry.catalog_key} value={entry.catalog_key}>
                  {entry.server_code} / {entry.tool_name}{entry.resource_kind ? ` · ${entry.resource_kind}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="tool-resource-deployment">精确 Resource Deployment</Label>
            <select id="tool-resource-deployment" name="resource_deployment_id" required={Boolean(selected?.resource_kind)} disabled={!selected?.resource_kind} className="h-9 w-full rounded-md border bg-background px-3 text-sm">
              <option value="">{selected?.resource_kind ? "请选择兼容且已启用的 Resource" : "此 Tool 不需要 Resource"}</option>
              {eligible.map((item) => <option key={item.deployment?.id} value={item.deployment?.id}>{item.resource.name} · {item.resource.kind} · {item.deployment?.generation_status || "UNAVAILABLE"}</option>)}
            </select>
            <p className="text-xs text-muted-foreground">只能从服务端返回的兼容 Deployment 中精确选择，不支持通配、字段映射或 SQL 模板。</p>
          </div>
          <div className="sm:col-span-2"><MutationNotice error={mutation.error} /></div>
          <Button type="submit" disabled={mutation.isPending}>创建 Draft</Button>
        </form>
      </CardContent>
    </Card>
  )
}

export function McpResourcesPage() {
  const user = useAuthenticatedUser()
  const query = useQuery({ queryKey: keys.resources, queryFn: listMcpResources })
  const client = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: (input: { code: string; action: "verify" | "publish" | "unpublish"; revision: number }) =>
      transitionMcpResource(input.code, input.action, input.revision),
    onSuccess: async () => client.invalidateQueries({ queryKey: keys.resources }),
  })
  return (
    <ManagementPage>
      <SectionHeading
        eyebrow="MCP Governance"
        title="Database / Redis / Loki Resource"
        description="页面展示启用/停用主状态，同时保留当前 Draft、验证、Deployment、Generation 与 Last Known Good 事实。新建和编辑将使用服务端拥有的安全表单 Schema。"
        action={
          <div className="flex gap-2">
            <RefreshButton query={query} />
            {user.capabilities.mcp_resources_manage ? (
              <Button type="button" onClick={() => { setCreating((value) => !value); setEditing(null) }}>
                <PlusIcon />新建 Resource
              </Button>
            ) : null}
          </div>
        }
      />
      {creating ? (
        <ResourceEditor
          onDone={async () => {
            setCreating(false)
            await client.invalidateQueries({ queryKey: keys.resources })
          }}
        />
      ) : null}
      {editing ? (
        <ExistingResourceEditor
          code={editing}
          onCancel={() => setEditing(null)}
          onDone={async () => {
            setEditing(null)
            await client.invalidateQueries({ queryKey: keys.resources })
          }}
        />
      ) : null}
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error} retry={() => void query.refetch()} />
      <MutationNotice error={mutation.error} />
      {query.data?.length === 0 ? (
        <EmptyCard icon={<DatabaseIcon />} title="暂无 MCP Resource" description="当前没有已登记的 Database、Redis 或 Loki Resource。" />
      ) : null}
      <div className="space-y-3">
        {query.data?.map((item) => {
          const active = item.deployment?.status === "ACTIVE"
          return (
            <Card key={item.resource.code} className="shadow-none">
              <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium">{item.resource.name}</p>
                    <Badge variant="outline">{item.resource.kind}</Badge>
                    <StatusBadge value={active ? "enabled" : "disabled"} />
                    {item.deployment?.generation_status ? <StatusBadge value={item.deployment.generation_status} /> : null}
                  </div>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {item.resource.code} · r{item.resource.revision}
                  </p>
                  {item.deployment?.safe_error_code ? (
                    <p className="mt-2 text-sm text-destructive">安全错误码：{item.deployment.safe_error_code}</p>
                  ) : null}
                </div>
                {user.capabilities.mcp_resources_manage ? (
                  <div className="flex gap-2">
                    <Button type="button" variant="outline" onClick={() => { setEditing(item.resource.code); setCreating(false) }}>
                      <PencilIcon />编辑
                    </Button>
                    {item.draft ? (
                      <Button type="button" variant="outline" onClick={() => mutation.mutate({ code: item.resource.code, action: "verify", revision: item.resource.revision })}>
                        校验候选
                      </Button>
                    ) : null}
                    {item.verification?.status === "PASSED" ? (
                      <Button type="button" onClick={() => mutation.mutate({ code: item.resource.code, action: "publish", revision: item.resource.revision })}>启用</Button>
                    ) : null}
                    {active ? (
                      <Button type="button" variant="outline" onClick={() => mutation.mutate({ code: item.resource.code, action: "unpublish", revision: item.resource.revision })}>停用</Button>
                    ) : null}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          )
        })}
      </div>
    </ManagementPage>
  )
}

function ExistingResourceEditor({
  code,
  onCancel,
  onDone,
}: {
  code: string
  onCancel: () => void
  onDone: () => Promise<void>
}) {
  const query = useQuery({
    queryKey: ["admin", "mcp", "resource-form", code],
    queryFn: () => getResourceForm(code),
  })
  if (query.isLoading) return <ManagementLoading />
  if (query.isError || !query.data) {
    return <ManagementError error={query.error} retry={() => void query.refetch()} />
  }
  return <ResourceEditor initial={query.data} onCancel={onCancel} onDone={onDone} />
}

function ResourceEditor({
  initial,
  onCancel,
  onDone,
}: {
  initial?: ResourceForm
  onCancel?: () => void
  onDone: () => Promise<void>
}) {
  const [kind, setKind] = useState<ResourceKind>(initial?.kind ?? "DATABASE")
  const credentials = useQuery({
    queryKey: ["admin", "mcp", "resource-credential-candidates"],
    queryFn: listResourceCredentialCandidates,
  })
  const mutation = useMutation({ mutationFn: saveResourceForm, onSuccess: onDone })
  const defaults = initial?.kind === kind ? initial : defaultResourceForm(kind)
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const common = {
      kind,
      code: String(data.get("code") || ""),
      name: String(data.get("name") || ""),
      expected_revision: Number(data.get("expected_revision") || 0),
    }
    if (kind === "DATABASE") {
      mutation.mutate({
        ...common,
        kind,
        provider: String(data.get("provider")) as "mysql" | "postgresql" | "sqlserver" | "oracle",
        host: String(data.get("host") || ""),
        port: Number(data.get("port") || 0),
        database_name: String(data.get("database_name") || ""),
        schema_name: String(data.get("schema_name") || ""),
        username: String(data.get("username") || ""),
        credential_id: String(data.get("credential_id") || ""),
        allowed_tables: splitValues(String(data.get("allowed_tables") || "")),
        max_rows: Number(data.get("max_rows") || 200),
        timeout_seconds: Number(data.get("timeout_seconds") || 10),
        tls: data.get("tls") === "on",
      })
    } else if (kind === "REDIS") {
      mutation.mutate({
        ...common,
        kind,
        host: String(data.get("host") || ""),
        port: Number(data.get("port") || 6379),
        redis_database: Number(data.get("redis_database") || 0),
        username: String(data.get("username") || ""),
        credential_id: String(data.get("credential_id") || ""),
        key_prefixes: splitValues(String(data.get("key_prefixes") || "")),
        scan_limit: Number(data.get("scan_limit") || 100),
        timeout_seconds: Number(data.get("timeout_seconds") || 10),
        tls: data.get("tls") === "on",
      })
    } else {
      mutation.mutate({
        ...common,
        kind,
        base_url: String(data.get("base_url") || ""),
        tenant_id: String(data.get("tenant_id") || ""),
        credential_id: String(data.get("credential_id") || ""),
        label_scope: parseLabels(String(data.get("label_scope") || "")),
        max_minutes: Number(data.get("max_minutes") || 60),
        max_lines: Number(data.get("max_lines") || 1000),
        timeout_seconds: Number(data.get("timeout_seconds") || 10),
      })
    }
  }
  return (
    <Card className="shadow-none">
      <CardHeader><CardTitle>{initial ? `编辑 ${initial.code}` : "新建 MCP Resource"}</CardTitle></CardHeader>
      <CardContent>
        <form className="grid gap-4 md:grid-cols-2" onSubmit={submit} key={`${initial?.code || "new"}:${kind}`}>
          <input type="hidden" name="expected_revision" value={defaults.expected_revision} />
          {initial ? <input type="hidden" name="code" value={defaults.code} /> : null}
          <div className="space-y-2">
            <Label htmlFor="resource-kind">类型</Label>
            <select id="resource-kind" className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={kind} disabled={Boolean(initial)} onChange={(event) => setKind(event.target.value as ResourceKind)}>
              <option value="DATABASE">Database</option><option value="REDIS">Redis</option><option value="LOKI">Loki</option>
            </select>
          </div>
          <TextField name="code" label="稳定代码" required defaultValue={defaults.code} disabled={Boolean(initial)} />
          <TextField name="name" label="显示名称" required defaultValue={defaults.name} />
          {kind === "DATABASE" ? <DatabaseFields value={defaults as Extract<ResourceForm, { kind: "DATABASE" }>} credentials={credentials.data ?? []} /> : null}
          {kind === "REDIS" ? <RedisFields value={defaults as Extract<ResourceForm, { kind: "REDIS" }>} credentials={credentials.data ?? []} /> : null}
          {kind === "LOKI" ? <LokiFields value={defaults as Extract<ResourceForm, { kind: "LOKI" }>} credentials={credentials.data ?? []} /> : null}
          <div className="md:col-span-2"><ManagementError error={credentials.error} retry={() => void credentials.refetch()} /><MutationNotice error={mutation.error} /></div>
          <div className="flex gap-2 md:col-span-2">
            <Button type="submit" disabled={mutation.isPending || credentials.isLoading}>保存 Draft</Button>
            {onCancel ? <Button type="button" variant="outline" onClick={onCancel}>取消</Button> : null}
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function DatabaseFields({ value, credentials }: { value: Extract<ResourceForm, { kind: "DATABASE" }>; credentials: CredentialSummary[] }) {
  return <>
    <div className="space-y-2"><Label htmlFor="resource-provider">数据库类型</Label><select id="resource-provider" name="provider" defaultValue={value.provider} className="h-9 w-full rounded-md border bg-background px-3 text-sm"><option value="postgresql">PostgreSQL</option><option value="mysql">MySQL</option><option value="sqlserver">SQL Server</option><option value="oracle">Oracle</option></select></div>
    <TextField name="host" label="Host" required defaultValue={value.host} />
    <TextField name="port" label="Port" required type="number" defaultValue={value.port} />
    <TextField name="database_name" label="Database" required defaultValue={value.database_name} />
    <TextField name="schema_name" label="Schema" defaultValue={value.schema_name} />
    <TextField name="username" label="只读用户名" required defaultValue={value.username} />
    <CredentialSelect credentials={credentials} value={value.credential_id} required />
    <TextField name="allowed_tables" label="允许表（逗号或换行分隔）" required defaultValue={value.allowed_tables.join(", ")} />
    <TextField name="max_rows" label="最大返回行数" required type="number" defaultValue={value.max_rows} />
    <TextField name="timeout_seconds" label="超时秒数" required type="number" defaultValue={value.timeout_seconds} />
    <BooleanField name="tls" label="启用 TLS" defaultChecked={value.tls} />
  </>
}

function RedisFields({ value, credentials }: { value: Extract<ResourceForm, { kind: "REDIS" }>; credentials: CredentialSummary[] }) {
  return <>
    <TextField name="host" label="Host" required defaultValue={value.host} />
    <TextField name="port" label="Port" required type="number" defaultValue={value.port} />
    <TextField name="redis_database" label="Database 编号" required type="number" defaultValue={value.redis_database} />
    <TextField name="username" label="用户名（可选）" defaultValue={value.username} />
    <CredentialSelect credentials={credentials} value={value.credential_id} />
    <TextField name="key_prefixes" label="允许 Key 前缀（逗号或换行分隔）" required defaultValue={value.key_prefixes.join(", ")} />
    <TextField name="scan_limit" label="扫描上限" required type="number" defaultValue={value.scan_limit} />
    <TextField name="timeout_seconds" label="超时秒数" required type="number" defaultValue={value.timeout_seconds} />
    <BooleanField name="tls" label="启用 TLS" defaultChecked={value.tls} />
  </>
}

function LokiFields({ value, credentials }: { value: Extract<ResourceForm, { kind: "LOKI" }>; credentials: CredentialSummary[] }) {
  return <>
    <TextField name="base_url" label="Loki Base URL" required defaultValue={value.base_url} />
    <TextField name="tenant_id" label="Tenant ID（可选）" defaultValue={value.tenant_id} />
    <CredentialSelect credentials={credentials} value={value.credential_id} />
    <TextField name="label_scope" label="标签范围（每行 key=value）" required defaultValue={Object.entries(value.label_scope).map(([key, item]) => `${key}=${item}`).join("\n")} />
    <TextField name="max_minutes" label="最大时间窗口（分钟）" required type="number" defaultValue={value.max_minutes} />
    <TextField name="max_lines" label="最大日志行数" required type="number" defaultValue={value.max_lines} />
    <TextField name="timeout_seconds" label="超时秒数" required type="number" defaultValue={value.timeout_seconds} />
  </>
}

function CredentialSelect({ credentials, value, required = false }: { credentials: CredentialSummary[]; value: string; required?: boolean }) {
  return <div className="space-y-2"><Label htmlFor="resource-credential">Credential</Label><select id="resource-credential" name="credential_id" defaultValue={value} required={required} className="h-9 w-full rounded-md border bg-background px-3 text-sm"><option value="">{required ? "请选择 Credential" : "无需认证"}</option>{credentials.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.purpose || "未标注用途"} · {item.masked_summary}</option>)}</select><p className="text-xs text-muted-foreground">浏览器只提交 Credential ID，内部 Secret Ref 仅由服务端解析。</p></div>
}

function BooleanField({ name, label, defaultChecked }: { name: string; label: string; defaultChecked: boolean }) {
  return <label className="flex items-center gap-2 self-end rounded-md border px-3 py-2 text-sm"><input name={name} type="checkbox" defaultChecked={defaultChecked} />{label}</label>
}

function defaultResourceForm(kind: ResourceKind): ResourceForm {
  const common = { code: "", name: "", expected_revision: 0 }
  if (kind === "DATABASE") return { ...common, kind, provider: "postgresql", host: "", port: 5432, database_name: "", schema_name: "public", username: "", credential_id: "", allowed_tables: [], max_rows: 200, timeout_seconds: 10, tls: true }
  if (kind === "REDIS") return { ...common, kind, host: "", port: 6379, redis_database: 0, username: "", credential_id: "", key_prefixes: [], scan_limit: 100, timeout_seconds: 10, tls: true }
  return { ...common, kind, base_url: "", tenant_id: "", credential_id: "", label_scope: {}, max_minutes: 60, max_lines: 1000, timeout_seconds: 10 }
}

function splitValues(value: string) {
  return [...new Set(value.split(/[\n,]/u).map((item) => item.trim()).filter(Boolean))]
}

function parseLabels(value: string) {
  return Object.fromEntries(
    value.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
      const separator = line.indexOf("=")
      return separator > 0 ? [line.slice(0, separator).trim(), line.slice(separator + 1).trim()] : [line, ""]
    })
  )
}

export function CredentialsPage() {
  const user = useAuthenticatedUser()
  const query = useQuery({ queryKey: keys.credentials, queryFn: listCredentials })
  const client = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [rotating, setRotating] = useState<CredentialSummary | null>(null)
  const disable = useMutation({
    mutationFn: (credential: CredentialSummary) => disableCredential(credential.code, credential.revision),
    onSuccess: async () => client.invalidateQueries({ queryKey: keys.credentials }),
  })
  return (
    <ManagementPage>
      <SectionHeading
        eyebrow="MCP Governance"
        title="Credential Center"
        description="凭据值使用 AES-256-GCM-AAD 加密保存；浏览器只接收 Credential ID、状态和脱敏摘要，不接收内部 Secret Ref 或密文。"
        action={
          <div className="flex gap-2">
            <RefreshButton query={query} />
            {user.capabilities.secrets_manage ? (
              <Button type="button" onClick={() => setCreating((value) => !value)}><PlusIcon />新建 Credential</Button>
            ) : null}
          </div>
        }
      />
      {creating ? <CredentialForm mode="create" onDone={async () => { setCreating(false); await client.invalidateQueries({ queryKey: keys.credentials }) }} /> : null}
      {rotating ? <CredentialForm mode="rotate" credential={rotating} onDone={async () => { setRotating(null); await client.invalidateQueries({ queryKey: keys.credentials }) }} /> : null}
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error} retry={() => void query.refetch()} />
      <MutationNotice error={disable.error} />
      <div className="grid gap-4 lg:grid-cols-2">
        {query.data?.map((credential) => (
          <Card key={credential.id} className="shadow-none">
            <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
              <div>
                <div className="flex items-center gap-2">
                  <KeyRoundIcon className="size-4" />
                  <p className="font-medium">{credential.code}</p>
                  <StatusBadge value={credential.status} />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {credential.purpose || "未填写用途"} · version {credential.active_version} · {credential.masked_summary}
                </p>
              </div>
              {user.capabilities.secrets_manage && credential.status === "enabled" ? (
                <div className="flex gap-2">
                  <Button type="button" variant="outline" onClick={() => setRotating(credential)}><RotateCwIcon />轮换</Button>
                  <Button type="button" variant="outline" disabled={disable.isPending} onClick={() => disable.mutate(credential)}><SquareIcon />停用</Button>
                </div>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>
    </ManagementPage>
  )
}

function CredentialForm({
  mode,
  credential,
  onDone,
}: {
  mode: "create" | "rotate"
  credential?: CredentialSummary
  onDone: () => Promise<void>
}) {
  const mutation = useMutation({
    mutationFn: (input: { code: string; purpose: string; value: string }) =>
      mode === "create"
        ? createCredential(input)
        : rotateCredential(credential!.code, credential!.revision, input.value),
    onSuccess: onDone,
  })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    mutation.mutate({
      code: credential?.code || String(data.get("code") || ""),
      purpose: String(data.get("purpose") || ""),
      value: String(data.get("value") || ""),
    })
  }
  return (
    <Card className="shadow-none">
      <CardHeader><CardTitle>{mode === "create" ? "新建 Credential" : `轮换 ${credential?.code}`}</CardTitle></CardHeader>
      <CardContent>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
          {mode === "create" ? <TextField name="code" label="代码" required /> : null}
          {mode === "create" ? <TextField name="purpose" label="用途" /> : null}
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor={`credential-value-${mode}`}>凭据值</Label>
            <Input id={`credential-value-${mode}`} name="value" type="password" autoComplete="new-password" required />
            <p className="text-xs text-muted-foreground">提交后不会再次显示，也不会写入前端缓存。</p>
          </div>
          <div className="sm:col-span-2"><MutationNotice error={mutation.error} /></div>
          <Button type="submit" disabled={mutation.isPending}>{mode === "create" ? "加密保存" : "确认轮换"}</Button>
        </form>
      </CardContent>
    </Card>
  )
}

function RefreshButton({ query }: { query: { isFetching: boolean; refetch: () => unknown } }) {
  return (
    <Button type="button" variant="outline" disabled={query.isFetching} onClick={() => void query.refetch()}>
      <RefreshCwIcon className={query.isFetching ? "animate-spin" : ""} />刷新
    </Button>
  )
}

function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase()
  const positive = ["ok", "ready", "active", "enabled", "published", "verified", "passed"].includes(normalized)
  return <Badge variant={positive ? "secondary" : "outline"}>{statusLabel(value)}</Badge>
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    ok: "正常", ready: "就绪", active: "启用", enabled: "启用", disabled: "停用",
    unavailable: "不可用", degraded: "降级", building: "装载中", failed: "失败",
    draft: "草稿", verified: "已校验", published: "已发布", passed: "通过",
  }
  return labels[value.toLowerCase()] || value
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 font-medium">{value}</p></div>
}

function TextField({ name, label, required = false, defaultValue, disabled = false, type = "text" }: { name: string; label: string; required?: boolean; defaultValue?: string | number; disabled?: boolean; type?: string }) {
  const id = `field-${name}`
  return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><Input id={id} name={name} type={type} required={required} defaultValue={defaultValue} disabled={disabled} /></div>
}

function EmptyCard({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return <Card className="shadow-none"><CardContent className="p-10 text-center"><span className="mx-auto block w-fit text-muted-foreground">{icon}</span><p className="mt-3 font-medium">{title}</p><p className="mt-1 text-sm text-muted-foreground">{description}</p></CardContent></Card>
}
