import { useState } from "react"
import {
  ArchiveIcon,
  CheckCircle2Icon,
  FlaskConicalIcon,
  LoaderCircleIcon,
  NetworkIcon,
  PlusIcon,
  SaveIcon,
  SendIcon,
  ShieldCheckIcon,
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
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import {
  useApiCapabilities,
  useApiConnections,
  useCopyCapabilityRelease,
  useCreateApiConnection,
  useInitializeOnesSearch,
  usePublishApiCapability,
  usePublishApiConnection,
  useSaveApiCapabilityDraft,
  useSaveApiConnectionDraft,
  useTestApiCapability,
  useUpdateApiConnectionRevision,
  useUpdateCapabilityRelease,
  useVerifyApiCapability,
  useVerifyApiConnection,
} from "@/contexts/api-capabilities/application/api-capability-queries"
import {
  authenticationProfileSchema,
  assertSafePreview,
  defaultOnesAuthenticationProfile,
  parseJsonObject,
  type ApiCapability,
  type ApiConnection,
  type AuthenticationProfile,
  type CapabilityPreview,
  type ConnectionDraftInput,
} from "@/contexts/api-capabilities/domain/api-capability"
import { ApiError } from "@/shared/api/api-client"

export function ApiCapabilityConfigurationPage() {
  const connections = useApiConnections()
  const capabilities = useApiCapabilities()
  const [connectionId, setConnectionId] = useState("")
  const [capabilityId, setCapabilityId] = useState("")

  if (connections.isLoading || capabilities.isLoading) {
    return (
      <main className="mx-auto w-full max-w-[1500px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-[36rem] w-full" />
      </main>
    )
  }

  const effectiveConnectionId = connectionId || connections.data?.[0]?.id || ""
  const effectiveCapabilityId = capabilityId || capabilities.data?.[0]?.id || ""
  const selectedConnection = connections.data?.find(
    (item) => item.id === effectiveConnectionId,
  )
  const selectedCapability = capabilities.data?.find(
    (item) => item.id === effectiveCapabilityId,
  )

  return (
    <main className="mx-auto w-full max-w-[1500px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            API Capability 配置
          </h1>
          <Badge variant="outline">无全局开关</Badge>
        </div>
        <p className="mt-1 max-w-4xl text-sm leading-6 text-muted-foreground">
          一个页面完成固定 Origin、认证协议、业务 Capability、HTTP Handler
          和受限 Mapping 的配置。发布为原子快照；Agent 与应用仍需分别选择精确
          Release 才能调用。
        </p>
      </header>

      <RequestFailure error={connections.error || capabilities.error} />

      <Tabs defaultValue="capabilities">
        <TabsList>
          <TabsTrigger value="capabilities">Capability 工作台</TabsTrigger>
          <TabsTrigger value="connections">Connection 与认证</TabsTrigger>
        </TabsList>
        <TabsContent value="capabilities" className="space-y-5">
          <CapabilitySelector
            capabilities={capabilities.data ?? []}
            selectedId={effectiveCapabilityId}
            onSelect={setCapabilityId}
            connections={connections.data ?? []}
          />
          {selectedCapability ? (
            <CapabilityWorkbench
              key={`${selectedCapability.id}:${selectedCapability.revision}:${selectedCapability.draft?.draft_revision ?? 0}`}
              capability={selectedCapability}
              connections={connections.data ?? []}
            />
          ) : (
            <EmptyState text="请先发布 ONES Connection，再初始化工作项搜索 Capability。" />
          )}
        </TabsContent>
        <TabsContent value="connections" className="space-y-5">
          <ConnectionSelector
            connections={connections.data ?? []}
            selectedId={effectiveConnectionId}
            onSelect={setConnectionId}
          />
          {selectedConnection ? (
            <ConnectionWorkbench
              key={`${selectedConnection.id}:${selectedConnection.revision}:${selectedConnection.draft?.draft_revision ?? 0}`}
              connection={selectedConnection}
            />
          ) : (
            <CreateConnectionCard />
          )}
        </TabsContent>
      </Tabs>
    </main>
  )
}

function ConnectionSelector({
  connections,
  selectedId,
  onSelect,
}: {
  connections: ApiConnection[]
  selectedId: string
  onSelect: (value: string) => void
}) {
  return (
    <Card className="shadow-none">
      <CardContent className="flex flex-wrap items-center gap-3 py-4">
        <NetworkIcon className="size-4 text-indigo-600" aria-hidden="true" />
        <label htmlFor="connection-select" className="text-sm font-medium">
          ONES Connection
        </label>
        <select
          id="connection-select"
          className={selectClass}
          value={selectedId}
          onChange={(event) => onSelect(event.target.value)}
        >
          <option value="">新建 Connection</option>
          {connections.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.code}
            </option>
          ))}
        </select>
      </CardContent>
    </Card>
  )
}

function CreateConnectionCard() {
  const mutation = useCreateApiConnection()
  const [code, setCode] = useState("ones-main")
  const [name, setName] = useState("ONES 主实例")
  const [origin, setOrigin] = useState<ConnectionDraftInput["origin"]>({
    scheme: "https",
    host: "",
    port: 443,
    allow_plain_http: false,
    connect_timeout_ms: 3000,
    read_timeout_ms: 10000,
    max_response_bytes: 1048576,
  })
  const [profileText, setProfileText] = useState(
    pretty(defaultOnesAuthenticationProfile),
  )
  const [localError, setLocalError] = useState("")

  const create = async () => {
    setLocalError("")
    try {
      await mutation.mutateAsync({
        code: code.trim(),
        name: name.trim(),
        origin,
        authentication: parseAuthentication(profileText),
      })
      toast.success("Connection Draft 已创建")
    } catch (error) {
      if (!(error instanceof ApiError)) {
        setLocalError(messageOf(error))
      }
    }
  }

  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>新建 ONES Connection</CardTitle>
        <CardDescription>
          Origin 必须固定；HTTPS 为默认值，企业内网或本地 ONES 使用 HTTP
          时必须显式接受明文传输风险。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 md:grid-cols-2">
          <LabeledInput label="编码" value={code} onChange={setCode} />
          <LabeledInput label="名称" value={name} onChange={setName} />
        </div>
        <OriginFields value={origin} onChange={setOrigin} />
        <JsonField
          label="Authentication Profile v1"
          value={profileText}
          onChange={setProfileText}
          rows={16}
        />
        <LocalFailure message={localError} />
        <RequestFailure error={mutation.error} />
        <Button onClick={() => void create()} disabled={mutation.isPending}>
          {mutation.isPending ? <LoaderCircleIcon className="animate-spin" /> : <PlusIcon />}
          创建草稿
        </Button>
      </CardContent>
    </Card>
  )
}

function ConnectionWorkbench({ connection }: { connection: ApiConnection }) {
  const draft = connection.draft
  const save = useSaveApiConnectionDraft(connection.id)
  const verify = useVerifyApiConnection(connection.id)
  const publish = usePublishApiConnection(connection.id)
  const updateRevision = useUpdateApiConnectionRevision()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [localError, setLocalError] = useState("")
  const [origin, setOrigin] = useState<ConnectionDraftInput["origin"]>(() => ({
    scheme: draft?.origin_scheme === "http" ? "http" : "https",
    host: draft?.origin_host ?? "",
    port: draft?.origin_port ?? 443,
    allow_plain_http: draft?.allow_plain_http ?? false,
    connect_timeout_ms: draft?.connect_timeout_ms ?? 3000,
    read_timeout_ms: draft?.read_timeout_ms ?? 10000,
    max_response_bytes: draft?.max_response_bytes ?? 1048576,
  }))
  const [profileText, setProfileText] = useState(
    pretty(draft?.authentication_profile.config ?? defaultOnesAuthenticationProfile),
  )

  if (!draft) return <EmptyState text="Connection 草稿不存在，无法继续配置。" />

  const saveDraft = async () => {
    setLocalError("")
    try {
      await save.mutateAsync({
        expected_revision: draft.draft_revision,
        origin,
        authentication: parseAuthentication(profileText),
      })
      toast.success("Connection Draft 已保存，原验证证据已按内容变化处理")
    } catch (error) {
      if (!(error instanceof ApiError)) setLocalError(messageOf(error))
    }
  }
  const verifyDraft = async () => {
    try {
      const result = await verify.mutateAsync({
        draft_revision: draft.draft_revision,
        draft_hash: draft.content_hash,
        email: email.trim(),
        password,
      })
      toast.success(
        `验证通过：${result.subject.display_name}，${result.subject.teams.length} 个 Team`,
      )
    } finally {
      setPassword("")
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_26rem]">
      <div className="space-y-5">
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>Connection Draft</CardTitle>
            <CardDescription>
              当前真实生效边界是固定 Origin 与同 Origin 认证传播；不声明 CIDR
              或完整网络区隔。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <OriginFields value={origin} onChange={setOrigin} />
            <JsonField
              label="Authentication Profile v1"
              value={profileText}
              onChange={setProfileText}
              rows={16}
            />
            <LocalFailure message={localError} />
            <RequestFailure error={save.error} />
            <Button onClick={() => void saveDraft()} disabled={save.isPending}>
              <SaveIcon />
              保存 Connection 与 Auth Profile
            </Button>
          </CardContent>
        </Card>

        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>首连接临时自验证</CardTitle>
            <CardDescription>
              邮箱和密码仅用于这次验证；密码、Token、Cookie、认证 Header
              和原始响应不会进入持久化或响应。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <LabeledInput
                label="当前管理员 ONES 邮箱"
                value={email}
                type="email"
                autoComplete="username"
                onChange={setEmail}
              />
              <LabeledInput
                label="一次性密码"
                value={password}
                type="password"
                autoComplete="current-password"
                onChange={setPassword}
              />
            </div>
            <RequestFailure error={verify.error || publish.error} />
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={verify.isPending || !email || !password}
                onClick={() => void verifyDraft()}
              >
                <ShieldCheckIcon />
                Verify
              </Button>
              <Button
                disabled={publish.isPending || draft.status !== "VERIFIED"}
                onClick={() =>
                  publish.mutate(
                    {
                      draft_revision: draft.draft_revision,
                      draft_hash: draft.content_hash,
                    },
                    { onSuccess: () => toast.success("Connection Revision 已发布") },
                  )
                }
              >
                <SendIcon />
                Publish
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="h-fit shadow-none">
        <CardHeader>
          <CardTitle>发布历史</CardTitle>
          <CardDescription>
            新 Revision 不改写历史。DISABLED 可恢复，ARCHIVED 不可恢复。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {connection.published_revisions.map((revision) => (
            <article key={revision.id} className="space-y-3 rounded-lg border p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">r{revision.revision}</span>
                <StatusBadge status={revision.status} />
              </div>
              <p className="text-xs text-muted-foreground">
                {revision.origin_scheme}://{revision.origin_host}:{revision.origin_port}
              </p>
              <div className="flex flex-wrap gap-2">
                {revision.status === "DISABLED" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      updateRevision.mutate({
                        revisionId: revision.id,
                        status: "PUBLISHED",
                      })
                    }
                  >
                    恢复
                  </Button>
                ) : null}
                {revision.status === "PUBLISHED" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      updateRevision.mutate({
                        revisionId: revision.id,
                        status: "DISABLED",
                      })
                    }
                  >
                    停用
                  </Button>
                ) : null}
                {revision.status !== "ARCHIVED" ? (
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() =>
                      updateRevision.mutate({
                        revisionId: revision.id,
                        status: "ARCHIVED",
                      })
                    }
                  >
                    <ArchiveIcon />
                    归档
                  </Button>
                ) : null}
              </div>
            </article>
          ))}
          {connection.published_revisions.length === 0 ? (
            <p className="text-sm text-muted-foreground">尚未发布 Revision。</p>
          ) : null}
          <RequestFailure error={updateRevision.error} />
        </CardContent>
      </Card>
    </div>
  )
}

function CapabilitySelector({
  capabilities,
  selectedId,
  onSelect,
  connections,
}: {
  capabilities: ApiCapability[]
  selectedId: string
  onSelect: (value: string) => void
  connections: ApiConnection[]
}) {
  const initialize = useInitializeOnesSearch()
  const published = connections.flatMap((item) => item.published_revisions)
    .find((item) => item.status === "PUBLISHED")
  return (
    <Card className="shadow-none">
      <CardContent className="flex flex-wrap items-center gap-3 py-4">
        <ShieldCheckIcon className="size-4 text-indigo-600" aria-hidden="true" />
        <label htmlFor="capability-select" className="text-sm font-medium">
          Capability
        </label>
        <select
          id="capability-select"
          className={selectClass}
          value={selectedId}
          onChange={(event) => onSelect(event.target.value)}
        >
          <option value="">请选择 Capability</option>
          {capabilities.map((item) => (
            <option key={item.id} value={item.id}>
              {item.identifier}
            </option>
          ))}
        </select>
        <Button
          className="ml-auto"
          variant="outline"
          disabled={!published || initialize.isPending}
          onClick={() =>
            published &&
            initialize.mutate(
              {
                connection_revision_id: published.id,
                authentication_profile_revision_id:
                  published.authentication_profile_revision_id,
              },
              { onSuccess: () => toast.success("ONES 工作项搜索模板已就绪") },
            )
          }
        >
          <PlusIcon />
          初始化 ONES 工作项搜索
        </Button>
        <RequestFailure error={initialize.error} />
      </CardContent>
    </Card>
  )
}

function CapabilityWorkbench({
  capability,
  connections,
}: {
  capability: ApiCapability
  connections: ApiConnection[]
}) {
  const draft = capability.draft
  const save = useSaveApiCapabilityDraft(capability.id)
  const test = useTestApiCapability(capability.id)
  const verify = useVerifyApiCapability(capability.id)
  const publish = usePublishApiCapability(capability.id)
  const [connectionRevisionId, setConnectionRevisionId] = useState(
    draft?.connection_revision_id ?? "",
  )
  const [name, setName] = useState(draft?.capability.name ?? capability.name)
  const [description, setDescription] = useState(
    draft?.capability.description ?? "",
  )
  const [method, setMethod] = useState<"GET" | "POST">(
    draft?.handler.method ?? "POST",
  )
  const [relativePath, setRelativePath] = useState(
    draft?.handler.relative_path ?? "",
  )
  const [graphqlDocument, setGraphqlDocument] = useState(
    draft?.handler.graphql_document ?? "",
  )
  const [inputSchema, setInputSchema] = useState(
    pretty(draft?.capability.input_schema ?? {}),
  )
  const [outputSchema, setOutputSchema] = useState(
    pretty(draft?.capability.output_schema ?? {}),
  )
  const [mapping, setMapping] = useState(pretty(draft?.mapping_ast ?? {}))
  const [testInput, setTestInput] = useState(
    pretty({ keyword: "登录", issue_type: "task", limit: 10 }),
  )
  const [releaseNote, setReleaseNote] = useState("")
  const [preview, setPreview] = useState<CapabilityPreview | null>(null)
  const [localError, setLocalError] = useState("")
  const publishedRevisions = connections.flatMap((item) =>
    item.published_revisions.map((revision) => ({
      ...revision,
      connectionName: item.name,
    })),
  )
  const selectedRevision = publishedRevisions.find(
    (item) => item.id === connectionRevisionId,
  )
  const input = (() => {
    if (!draft || !selectedRevision) return null
    try {
      return {
        expected_revision: draft.draft_revision,
        connection_revision_id: selectedRevision.id,
        authentication_profile_revision_id:
          selectedRevision.authentication_profile_revision_id,
        capability: {
          name: name.trim(),
          description: description.trim(),
          operation_semantics: "QUERY" as const,
          data_classification: "INTERNAL" as const,
          input_schema: parseJsonObject(inputSchema, "Input Schema"),
          output_schema: parseJsonObject(outputSchema, "Output Schema"),
        },
        handler: {
          method,
          relative_path: relativePath.trim(),
          graphql_document: graphqlDocument.trim(),
        },
        mapping_ast: parseJsonObject(mapping, "Mapping AST"),
      }
    } catch {
      return null
    }
  })()

  if (!draft) return <EmptyState text="Capability Draft 不存在。" />

  const parseDraft = () => {
    if (!selectedRevision) throw new Error("请选择可用的 Connection Revision")
    return {
      expected_revision: draft.draft_revision,
      connection_revision_id: selectedRevision.id,
      authentication_profile_revision_id:
        selectedRevision.authentication_profile_revision_id,
      capability: {
        name: name.trim(),
        description: description.trim(),
        operation_semantics: "QUERY" as const,
        data_classification: "INTERNAL" as const,
        input_schema: parseJsonObject(inputSchema, "Input Schema"),
        output_schema: parseJsonObject(outputSchema, "Output Schema"),
      },
      handler: {
        method,
        relative_path: relativePath.trim(),
        graphql_document: graphqlDocument.trim(),
      },
      mapping_ast: parseJsonObject(mapping, "Mapping AST"),
    }
  }
  const saveDraft = async () => {
    setLocalError("")
    try {
      await save.mutateAsync(parseDraft())
      setPreview(null)
      toast.success("Capability 五区域草稿已保存")
    } catch (error) {
      if (!(error instanceof ApiError)) setLocalError(messageOf(error))
    }
  }
  const run = async (mode: "test" | "verify") => {
    setLocalError("")
    try {
      const agentInput = parseJsonObject(testInput, "测试输入")
      const action = mode === "test" ? test : verify
      const result = await action.mutateAsync({
        draft_revision: draft.draft_revision,
        draft_hash: draft.content_hash,
        agent_input: agentInput,
      })
      const nextPreview = "preview" in result ? result.preview : result
      assertSafePreview(nextPreview)
      setPreview(nextPreview)
      toast.success(mode === "test" ? "Capability Test 通过" : "Capability Verify 通过")
    } catch (error) {
      if (!(error instanceof ApiError)) setLocalError(messageOf(error))
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-2">
        <RegionCard number="1" title="Capability 业务契约">
          <div className="grid gap-4 md:grid-cols-2">
            <LabeledInput label="名称" value={name} onChange={setName} />
            <StaticField label="Identifier" value={capability.identifier} mono />
          </div>
          <label className="space-y-2 text-sm">
            <span className="font-medium">业务备注 / description</span>
            <Textarea
              value={description}
              rows={4}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <Badge>QUERY</Badge>
            <Badge variant="outline">INTERNAL</Badge>
          </div>
        </RegionCard>

        <RegionCard number="2" title="固定 Connection">
          <label className="space-y-2 text-sm">
            <span className="font-medium">已发布 Connection Revision</span>
            <select
              className={selectClass}
              value={connectionRevisionId}
              onChange={(event) => setConnectionRevisionId(event.target.value)}
            >
              <option value="">请选择 Revision</option>
              {publishedRevisions
                .filter((item) => item.status === "PUBLISHED")
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.connectionName} · r{item.revision}
                  </option>
                ))}
            </select>
          </label>
          {selectedRevision ? (
            <StaticField
              label="真实生效 Origin"
              value={`${selectedRevision.origin_scheme}://${selectedRevision.origin_host}:${selectedRevision.origin_port}`}
              mono
            />
          ) : null}
        </RegionCard>

        <RegionCard number="3" title="Authentication Profile">
          <p className="text-sm leading-6 text-muted-foreground">
            Capability 只引用 Connection 冻结的认证 Profile Revision。
            Agent 输入不包含 Team、User ID、Token 或认证 Header。
          </p>
          <StaticField
            label="Profile Revision ID"
            value={selectedRevision?.authentication_profile_revision_id ?? "未选择"}
            mono
          />
        </RegionCard>

        <RegionCard number="4" title="Handler">
          <div className="grid gap-4 md:grid-cols-[9rem_1fr]">
            <label className="space-y-2 text-sm">
              <span className="font-medium">Method</span>
              <select
                className={selectClass}
                value={method}
                onChange={(event) => setMethod(event.target.value as "GET" | "POST")}
              >
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select>
            </label>
            <LabeledInput
              label="Relative Path"
              value={relativePath}
              onChange={setRelativePath}
            />
          </div>
          <label className="space-y-2 text-sm">
            <span className="font-medium">固定 GraphQL Query（可选）</span>
            <Textarea
              className="font-mono text-xs"
              value={graphqlDocument}
              rows={10}
              onChange={(event) => setGraphqlDocument(event.target.value)}
            />
          </label>
        </RegionCard>
      </div>

      <RegionCard number="5" title="公开 Schema 与受限 Mapping">
        <div className="grid gap-4 xl:grid-cols-3">
          <JsonField
            label="公开 Input Schema"
            value={inputSchema}
            onChange={setInputSchema}
            rows={18}
          />
          <JsonField
            label="公开 Output Schema"
            value={outputSchema}
            onChange={setOutputSchema}
            rows={18}
          />
          <JsonField
            label="Mapping AST v1"
            value={mapping}
            onChange={setMapping}
            rows={18}
          />
        </div>
      </RegionCard>

      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>保存 → Test → Verify → Publish</CardTitle>
          <CardDescription>
            任一五区域内容变化都会生成新草稿 Revision，并使旧验证证据失效。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <JsonField
            label="Capability Test 公开输入"
            value={testInput}
            onChange={setTestInput}
            rows={6}
          />
          <LabeledInput
            label="Release Note（只在管理端历史展示）"
            value={releaseNote}
            onChange={setReleaseNote}
          />
          <LocalFailure message={localError} />
          <RequestFailure
            error={save.error || test.error || verify.error || publish.error}
          />
          <FieldErrors
            error={save.error || test.error || verify.error || publish.error}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={save.isPending || !input}
              onClick={() => void saveDraft()}
            >
              <SaveIcon />
              保存五区域
            </Button>
            <Button
              variant="outline"
              disabled={test.isPending}
              onClick={() => void run("test")}
            >
              <FlaskConicalIcon />
              Test
            </Button>
            <Button
              variant="outline"
              disabled={verify.isPending}
              onClick={() => void run("verify")}
            >
              <CheckCircle2Icon />
              Verify
            </Button>
            <Button
              disabled={publish.isPending || draft.status !== "VERIFIED"}
              onClick={() =>
                publish.mutate(
                  {
                    draft_revision: draft.draft_revision,
                    draft_hash: draft.content_hash,
                    idempotency_key: `${capability.identifier}:${draft.content_hash}`,
                    release_note: releaseNote.trim(),
                  },
                  { onSuccess: () => toast.success("Capability Release 已发布") },
                )
              }
            >
              <SendIcon />
              Publish
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            当前草稿 r{draft.draft_revision} · {draft.status} · hash{" "}
            {draft.content_hash.slice(0, 16)}…
          </p>
        </CardContent>
      </Card>

      {preview ? <SafePreview preview={preview} /> : null}
      <CapabilityReleaseHistory capability={capability} />
    </div>
  )
}

function SafePreview({ preview }: { preview: CapabilityPreview }) {
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>结构化安全预览</CardTitle>
        <CardDescription>
          只包含普通业务字段；认证材料与原始响应在响应结构中不存在。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 xl:grid-cols-2">
        <JsonReadOnly
          label="请求"
          value={{
            method: preview.method,
            relative_path: preview.relative_path,
            query: preview.query,
            body: preview.body,
          }}
        />
        <JsonReadOnly label="规范化输出" value={preview.normalized_output} />
      </CardContent>
    </Card>
  )
}

function CapabilityReleaseHistory({ capability }: { capability: ApiCapability }) {
  const update = useUpdateCapabilityRelease()
  const copy = useCopyCapabilityRelease()
  const [reasonById, setReasonById] = useState<Record<string, string>>({})
  const [replacementById, setReplacementById] = useState<Record<string, string>>({})
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>Capability Release 历史</CardTitle>
        <CardDescription>
          历史发布不可变；废弃可指定替代版本，归档后不可恢复。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {capability.releases.map((release) => (
          <article key={release.id} className="space-y-3 rounded-lg border p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">Release r{release.release_revision}</span>
              <StatusBadge status={release.status} />
              <span className="text-xs text-muted-foreground">
                {release.release_note || "无发布备注"}
              </span>
            </div>
            <p className="text-sm text-muted-foreground">{release.description}</p>
            <div className="grid gap-3 md:grid-cols-2">
              <LabeledInput
                label="状态变更原因"
                value={reasonById[release.id] ?? ""}
                onChange={(value) =>
                  setReasonById({ ...reasonById, [release.id]: value })
                }
              />
              <label className="space-y-2 text-sm">
                <span className="font-medium">Replacement Release</span>
                <select
                  className={selectClass}
                  value={replacementById[release.id] ?? ""}
                  onChange={(event) =>
                    setReplacementById({
                      ...replacementById,
                      [release.id]: event.target.value,
                    })
                  }
                >
                  <option value="">不指定</option>
                  {capability.releases
                    .filter((item) => item.id !== release.id && item.status === "ACTIVE")
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        r{item.release_revision}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            <div className="flex flex-wrap gap-2">
              {release.status !== "ACTIVE" && release.status !== "ARCHIVED" ? (
                <ReleaseAction
                  label="恢复 ACTIVE"
                  onClick={() =>
                    update.mutate({
                      releaseId: release.id,
                      status: "ACTIVE",
                      reason: "",
                      replacement_release_id: "",
                    })
                  }
                />
              ) : null}
              {release.status === "ACTIVE" ? (
                <>
                  <ReleaseAction
                    label="废弃"
                    onClick={() =>
                      update.mutate({
                        releaseId: release.id,
                        status: "DEPRECATED",
                        reason: reasonById[release.id] ?? "",
                        replacement_release_id: replacementById[release.id] ?? "",
                      })
                    }
                  />
                  <ReleaseAction
                    label="停用"
                    onClick={() =>
                      update.mutate({
                        releaseId: release.id,
                        status: "DISABLED",
                        reason: reasonById[release.id] ?? "",
                        replacement_release_id: "",
                      })
                    }
                  />
                </>
              ) : null}
              {release.status !== "ARCHIVED" ? (
                <ReleaseAction
                  label="归档"
                  destructive
                  onClick={() =>
                    update.mutate({
                      releaseId: release.id,
                      status: "ARCHIVED",
                      reason: reasonById[release.id] ?? "",
                      replacement_release_id: "",
                    })
                  }
                />
              ) : null}
              <ReleaseAction
                label="复制为 Draft"
                onClick={() =>
                  copy.mutate({
                    releaseId: release.id,
                    expectedRevision: capability.draft?.draft_revision ?? capability.revision,
                  })
                }
              />
            </div>
          </article>
        ))}
        {capability.releases.length === 0 ? (
          <p className="text-sm text-muted-foreground">尚未发布 Release。</p>
        ) : null}
        <RequestFailure error={update.error || copy.error} />
      </CardContent>
    </Card>
  )
}

function RegionCard({
  number,
  title,
  children,
}: {
  number: string
  title: string
  children: React.ReactNode
}) {
  return (
    <Card className="shadow-none">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Badge className="rounded-full">{number}</Badge>
          <CardTitle>{title}</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  )
}

function OriginFields({
  value,
  onChange,
}: {
  value: ConnectionDraftInput["origin"]
  onChange: (value: ConnectionDraftInput["origin"]) => void
}) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <label className="space-y-2 text-sm">
        <span className="font-medium">Scheme</span>
        <select
          className={selectClass}
          value={value.scheme}
          onChange={(event) =>
            onChange({
              ...value,
              scheme: event.target.value as "https" | "http",
              allow_plain_http:
                event.target.value === "https" ? false : value.allow_plain_http,
            })
          }
        >
          <option value="https">https</option>
          <option value="http">http（需接受明文传输风险）</option>
        </select>
      </label>
      <LabeledInput
        label="固定 Host"
        value={value.host}
        onChange={(host) => onChange({ ...value, host })}
      />
      <LabeledInput
        label="Port"
        value={String(value.port)}
        type="number"
        onChange={(port) => onChange({ ...value, port: Number(port) })}
      />
      <LabeledInput
        label="连接超时 ms"
        value={String(value.connect_timeout_ms)}
        type="number"
        onChange={(connect_timeout_ms) =>
          onChange({ ...value, connect_timeout_ms: Number(connect_timeout_ms) })
        }
      />
      <LabeledInput
        label="读取超时 ms"
        value={String(value.read_timeout_ms)}
        type="number"
        onChange={(read_timeout_ms) =>
          onChange({ ...value, read_timeout_ms: Number(read_timeout_ms) })
        }
      />
      <LabeledInput
        label="最大响应 bytes"
        value={String(value.max_response_bytes)}
        type="number"
        onChange={(max_response_bytes) =>
          onChange({ ...value, max_response_bytes: Number(max_response_bytes) })
        }
      />
      <label className="flex items-center gap-2 text-sm md:col-span-3">
        <Checkbox
          checked={value.allow_plain_http}
          disabled={value.scheme !== "http"}
          onCheckedChange={(checked) =>
            onChange({ ...value, allow_plain_http: Boolean(checked) })
          }
        />
        允许明文 HTTP（密码、Token 和业务数据可能被窃听或篡改）
      </label>
    </div>
  )
}

function LabeledInput({
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  autoComplete?: string
}) {
  return (
    <label className="space-y-2 text-sm">
      <span className="font-medium">{label}</span>
      <Input
        type={type}
        autoComplete={autoComplete}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

function JsonField({
  label,
  value,
  onChange,
  rows,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  rows: number
}) {
  return (
    <label className="space-y-2 text-sm">
      <span className="font-medium">{label}</span>
      <Textarea
        className="font-mono text-xs"
        rows={rows}
        spellCheck={false}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

function StaticField({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="text-sm">
      <p className="font-medium">{label}</p>
      <p className={`mt-1 break-all text-muted-foreground ${mono ? "font-mono text-xs" : ""}`}>
        {value}
      </p>
    </div>
  )
}

function JsonReadOnly({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <p className="mb-2 text-sm font-medium">{label}</p>
      <pre className="max-h-96 overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-100">
        {pretty(value)}
      </pre>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={status === "ACTIVE" || status === "PUBLISHED" ? "secondary" : "outline"}>
      {status}
    </Badge>
  )
}

function ReleaseAction({
  label,
  onClick,
  destructive = false,
}: {
  label: string
  onClick: () => void
  destructive?: boolean
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant={destructive ? "destructive" : "outline"}
      onClick={onClick}
    >
      {label}
    </Button>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
      {text}
    </div>
  )
}

function LocalFailure({ message }: { message: string }) {
  return message ? <p role="alert" className="text-sm text-destructive">{message}</p> : null
}

function RequestFailure({ error }: { error: unknown }) {
  if (!error) return null
  const message =
    error instanceof ApiError && error.code === "revision_conflict"
      ? `${error.message} 页面已重新读取最新 Revision，请核对后再次保存。`
      : messageOf(error)
  return <p role="alert" className="text-sm text-destructive">{message}</p>
}

function FieldErrors({ error }: { error: unknown }) {
  if (!(error instanceof ApiError) || error.fieldErrors.length === 0) return null
  return (
    <ul className="space-y-1 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
      {error.fieldErrors.map((item, index) => (
        <li key={`${item.field}:${index}`}>
          <span className="font-mono">{item.field}</span>：{item.message}
        </li>
      ))}
    </ul>
  )
}

function parseAuthentication(value: string): AuthenticationProfile {
  return authenticationProfileSchema.parse(
    parseJsonObject(value, "Authentication Profile"),
  )
}

function pretty(value: unknown) {
  return JSON.stringify(value, null, 2)
}

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : "请求未能完成"
}

const selectClass =
  "h-8 min-w-56 rounded-lg border border-input bg-background px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
