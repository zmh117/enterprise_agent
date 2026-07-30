import { useState, type FormEvent } from "react"
import {
  BotIcon,
  CheckCircle2Icon,
  FlaskConicalIcon,
  KeyRoundIcon,
  LoaderCircleIcon,
  RotateCcwIcon,
  SaveIcon,
  SendIcon,
} from "lucide-react"
import { Link, useParams } from "react-router-dom"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  useAgentProfile,
  useAgentProfiles,
  useAgentPublications,
  useModelConnection,
  usePublishAgentDraft,
  useRollbackAgentPublication,
  useRotateCredential,
  useSaveAgentDraft,
  useSaveConnection,
  useTestConnection,
  useValidateAgentDraft,
} from "@/contexts/agent-profiles/application/agent-profile-queries"
import type {
  AgentConfig,
  ModelConnectionConfig,
} from "@/contexts/agent-profiles/domain/agent-profile"
import { ApiError } from "@/shared/api/api-client"

export function AgentProfilesPage() {
  const profiles = useAgentProfiles()
  if (profiles.isLoading) {
    return (
      <main className="mx-auto w-full max-w-[1400px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
        <Skeleton className="h-9 w-56" />
        <Skeleton className="h-48 w-full" />
      </main>
    )
  }
  if (profiles.isError || !profiles.data) {
    return (
      <main className="mx-auto w-full max-w-[1100px] px-4 py-8">
        <MutationMessage error={profiles.error} />
      </main>
    )
  }
  return (
    <main className="mx-auto w-full max-w-[1400px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Agent 配置</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          底层按多 Agent 建模；当前版本只允许编辑默认诊断 Agent。
        </p>
      </header>
      <div className="grid gap-4 lg:grid-cols-2">
        {profiles.data.map((profile) => (
          <Card key={profile.id} className="shadow-none">
            <CardContent className="space-y-4 py-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-semibold">{profile.name}</p>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {profile.code}
                  </p>
                </div>
                <Badge
                  variant={
                    profile.management_mode === "editable"
                      ? "secondary"
                      : "outline"
                  }
                >
                  {profile.management_mode === "editable" ? "可编辑" : "只读"}
                </Badge>
              </div>
              <div className="space-y-2 text-sm">
                <StatusLine
                  label="发布版本"
                  value={
                    profile.current_publication
                      ? `r${profile.current_publication.revision}`
                      : "未发布"
                  }
                />
                <StatusLine
                  label="模型连接"
                  value={modelConnectionStatusLabel(
                    profile.model_connection_status,
                  )}
                />
                <StatusLine
                  label="活动应用"
                  value={String(profile.active_application_count)}
                />
              </div>
              {profile.management_mode === "editable" ? (
                <Button
                  render={<Link to={`/agent-profiles/${profile.code}`} />}
                >
                  进入配置
                </Button>
              ) : (
                <p className="text-xs text-muted-foreground">
                  非默认 Agent 在当前 MVP 中不开放编辑。
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </main>
  )
}

export function AgentProfilePage() {
  const routeCode = useParams().code ?? "default-diagnostic-agent"
  const agent = useAgentProfile()
  const connection = useModelConnection()

  if (agent.isLoading || connection.isLoading) {
    return (
      <main className="mx-auto w-full max-w-[1500px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-[32rem] w-full" />
      </main>
    )
  }
  if (agent.isError || connection.isError || !agent.data || !connection.data) {
    const error = agent.error ?? connection.error
    return (
      <main className="mx-auto w-full max-w-[1100px] px-4 py-8">
        <Card className="border-destructive/40 shadow-none">
          <CardHeader>
            <CardTitle>Agent 配置无法加载</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <MutationMessage error={error} />
            <Button
              onClick={() => {
                void agent.refetch()
                void connection.refetch()
              }}
            >
              重试
            </Button>
          </CardContent>
        </Card>
      </main>
    )
  }
  if (routeCode !== "default-diagnostic-agent") {
    return (
      <main className="mx-auto w-full max-w-[900px] px-4 py-8">
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>当前 Agent 只读</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>
              第一版 UI 只开放默认诊断 Agent，不支持创建、复制或删除 Agent。
            </p>
            <Button variant="outline" render={<Link to="/agent-profiles" />}>
              返回 Agent 配置
            </Button>
          </CardContent>
        </Card>
      </main>
    )
  }
  return (
    <Workspace
      key={`${agent.data.draft?.revision ?? 0}:${connection.data.revision}`}
      agent={agent.data}
      connection={connection.data}
    />
  )
}

function Workspace({
  agent,
  connection,
}: {
  agent: NonNullable<ReturnType<typeof useAgentProfile>["data"]>
  connection: NonNullable<ReturnType<typeof useModelConnection>["data"]>
}) {
  const currentModel =
    connection.current_revision?.config.model ??
    agent.draft?.config.model_policy.model ??
    ""
  return (
    <main className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <BotIcon className="size-6 text-primary" aria-hidden="true" />
            <h1 className="text-2xl font-semibold tracking-tight">
              {agent.definition.name}
            </h1>
            <Badge variant="outline">唯一可编辑 Agent 配置</Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {agent.definition.code} · Claude Agent SDK · {currentModel}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge
            variant={
              connection.current_revision?.credential.configured &&
              !connection.current_revision.credential.rotation_required
                ? "secondary"
                : "destructive"
            }
          >
            {connection.current_revision?.credential.configured &&
            !connection.current_revision.credential.rotation_required
              ? "模型凭据已配置"
              : "需要轮换模型凭据"}
          </Badge>
          <Badge variant="outline">
            Agent r{agent.draft?.revision ?? agent.definition.revision}
          </Badge>
        </div>
      </header>

      <Card className="border-amber-300/70 bg-amber-50/40 shadow-none dark:bg-amber-950/10">
        <CardContent className="py-4 text-sm text-muted-foreground">
          发布 Agent 配置只会生成新的 Agent
          发布版本，不会自动切换任何业务应用。已激活应用仍使用它自己固定的
          Agent 发布版本，需进入应用详情手动更新并重新发布。
        </CardContent>
      </Card>

      <Tabs defaultValue="profile">
        <TabsList className="h-auto w-full justify-start overflow-x-auto">
          <TabsTrigger value="profile">Agent 配置</TabsTrigger>
          <TabsTrigger value="connection">模型连接</TabsTrigger>
          <TabsTrigger value="publications">发布历史</TabsTrigger>
        </TabsList>
        <TabsContent value="profile">
          <ProfileForm agent={agent} connection={connection} />
        </TabsContent>
        <TabsContent value="connection">
          <ConnectionForm
            connection={connection}
            canManageCredential={agent.permissions.can_manage_credential}
            canTestConnection={agent.permissions.can_test_connection}
          />
        </TabsContent>
        <TabsContent value="publications">
          <PublicationHistory
            currentId={agent.definition.current_publication_id ?? ""}
            canPublish={agent.permissions.can_publish}
          />
        </TabsContent>
      </Tabs>
    </main>
  )
}

function ConnectionForm({
  connection,
  canManageCredential,
  canTestConnection,
}: {
  connection: NonNullable<ReturnType<typeof useModelConnection>["data"]>
  canManageCredential: boolean
  canTestConnection: boolean
}) {
  const current = connection.current_revision
  const save = useSaveConnection()
  const test = useTestConnection()
  const [saveError, setSaveError] = useState<unknown>(null)
  const [form, setForm] = useState<
    Omit<ModelConnectionConfig, "schema_version">
  >({
    protocol: "anthropic_compatible",
    base_url: current?.config.base_url ?? "",
    model: current?.config.model ?? "",
    default_opus_model: current?.config.default_opus_model ?? "",
    default_sonnet_model: current?.config.default_sonnet_model ?? "",
    default_haiku_model: current?.config.default_haiku_model ?? "",
    subagent_model: current?.config.subagent_model ?? "",
    effort_level: current?.config.effort_level ?? "max",
  })

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaveError(null)
    try {
      const revision = await save.mutateAsync({
        expected_revision: connection.revision,
        config: form,
      })
      toast.success(`模型连接 r${revision.revision} 已保存`)
    } catch (error) {
      setSaveError(error)
    } finally {
      // Do not leave the plaintext credential in TanStack Mutation variables.
      save.reset()
    }
  }

  return (
    <form
      onSubmit={submit}
      className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]"
    >
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>Anthropic 兼容连接</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="协议" htmlFor="model-protocol">
              <Input
                id="model-protocol"
                value="anthropic_compatible"
                disabled
              />
            </Field>
            <Field label="服务地址（Base URL）" htmlFor="model-base-url">
              <Input
                id="model-base-url"
                value={form.base_url}
                onChange={(event) =>
                  setForm({ ...form, base_url: event.target.value })
                }
                placeholder="https://api.deepseek.com/anthropic"
                required
              />
            </Field>
            <Field label="主模型" htmlFor="model-primary">
              <Input
                id="model-primary"
                value={form.model}
                onChange={(event) =>
                  setForm({ ...form, model: event.target.value })
                }
                required
              />
            </Field>
            <Field label="Opus 默认模型" htmlFor="model-opus">
              <Input
                id="model-opus"
                value={form.default_opus_model}
                onChange={(event) =>
                  setForm({ ...form, default_opus_model: event.target.value })
                }
                placeholder="留空则继承主模型"
              />
            </Field>
            <Field label="Sonnet 默认模型" htmlFor="model-sonnet">
              <Input
                id="model-sonnet"
                value={form.default_sonnet_model}
                onChange={(event) =>
                  setForm({ ...form, default_sonnet_model: event.target.value })
                }
                placeholder="留空则继承主模型"
              />
            </Field>
            <Field label="Haiku 默认模型" htmlFor="model-haiku">
              <Input
                id="model-haiku"
                value={form.default_haiku_model}
                onChange={(event) =>
                  setForm({ ...form, default_haiku_model: event.target.value })
                }
                placeholder="留空则继承主模型"
              />
            </Field>
            <Field label="子 Agent 模型" htmlFor="model-subagent">
              <Input
                id="model-subagent"
                value={form.subagent_model}
                onChange={(event) =>
                  setForm({ ...form, subagent_model: event.target.value })
                }
                placeholder="留空则继承主模型"
              />
            </Field>
            <Field label="推理强度" htmlFor="model-effort">
              <select
                id="model-effort"
                className={selectClass}
                value={form.effort_level}
                onChange={(event) =>
                  setForm({
                    ...form,
                    effort_level: event.target
                      .value as typeof form.effort_level,
                  })
                }
              >
                {["low", "medium", "high", "max"].map((value) => (
                  <option key={value} value={value}>
                    {
                      {
                        low: "低",
                        medium: "中",
                        high: "高",
                        max: "最高",
                      }[value]
                    }
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <MutationMessage error={saveError} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <SaveIcon />
              )}
              保存为新连接版本
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={
                test.isPending ||
                !current ||
                !current.credential.configured ||
                current.credential.rotation_required ||
                !canTestConnection
              }
              onClick={() => current && test.mutate(current.id)}
            >
              {test.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <FlaskConicalIcon />
              )}
              测试已保存版本
            </Button>
          </div>
          <MutationMessage error={test.error} />
          {test.data ? (
            <p className="text-sm text-emerald-700">
              连接成功 · {test.data.provider_host} · {test.data.model} ·{" "}
              {test.data.duration_ms}ms
            </p>
          ) : null}
        </CardContent>
      </Card>

      <div className="space-y-5">
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>当前凭据</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {current ? (
              <>
                <StatusLine
                  label="状态"
                  value={
                    current.credential.configured &&
                    !current.credential.rotation_required
                      ? "已配置"
                      : "需要轮换"
                  }
                />
                <StatusLine
                  label="脱敏值"
                  value={current.credential.masked || "未保存"}
                  mono
                />
                <StatusLine
                  label="凭据版本"
                  value={`v${current.credential.version}`}
                />
                <StatusLine
                  label="连接版本"
                  value={`r${current.revision}`}
                />
                <StatusLine
                  label="提供方主机"
                  value={current.provider_host}
                  mono
                />
                <CredentialSheet
                  connectionRevision={connection.revision}
                  configured={current.credential.configured}
                  allowed={canManageCredential}
                />
              </>
            ) : (
              <p className="text-muted-foreground">
                请先保存连接配置，再配置 API Key。
              </p>
            )}
            {!canManageCredential ? (
              <p className="text-xs text-muted-foreground">
                当前账号没有凭据管理权限，只能查看凭据状态。
              </p>
            ) : null}
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>安全边界</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>仅允许 HTTPS 和部署侧提供方主机允许列表。</p>
            <p>拒绝 URL 用户信息、fragment、私网和环回 DNS 结果。</p>
            <p>连接测试只能使用已保存 revision 和加密凭据。</p>
          </CardContent>
        </Card>
      </div>
    </form>
  )
}

function CredentialSheet({
  connectionRevision,
  configured,
  allowed,
}: {
  connectionRevision: number
  configured: boolean
  allowed: boolean
}) {
  const [open, setOpen] = useState(false)
  const [apiKey, setApiKey] = useState("")
  const [error, setError] = useState<unknown>(null)
  const rotate = useRotateCredential()

  function resetPlaintext() {
    setApiKey("")
    setError(null)
    rotate.reset()
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const revision = await rotate.mutateAsync({
        expected_revision: connectionRevision,
        api_key: apiKey,
      })
      toast.success(`模型凭据已轮换为 v${revision.credential.version}`)
      resetPlaintext()
      setOpen(false)
    } catch (caught) {
      setError(caught)
    } finally {
      // Do not retain plaintext in TanStack Mutation variables.
      rotate.reset()
    }
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) resetPlaintext()
      }}
    >
      <SheetTrigger
        render={
          <Button className="mt-2 w-full" variant="outline">
            <KeyRoundIcon />
            {configured ? "轮换 API Key" : "配置 API Key"}
          </Button>
        }
        disabled={!allowed}
      />
      <SheetContent>
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <SheetHeader>
            <SheetTitle>
              {configured ? "轮换 API Key" : "配置 API Key"}
            </SheetTitle>
            <SheetDescription>
              输入值只发送到加密凭据接口。关闭或保存后立即清空，不会回显旧值。
            </SheetDescription>
          </SheetHeader>
          <div className="flex-1 space-y-4 overflow-y-auto px-4">
            <Field label="新的 API Key" htmlFor="model-api-key">
              <Input
                id="model-api-key"
                type="password"
                autoComplete="new-password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder="输入新的 API Key"
                required
              />
            </Field>
            <MutationMessage error={error} />
            <p className="text-xs leading-5 text-muted-foreground">
              应先在模型提供方撤销旧 Key。保存成功后只显示脱敏摘要和活动版本。
            </p>
          </div>
          <SheetFooter>
            <Button type="submit" disabled={rotate.isPending || !apiKey}>
              {rotate.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <KeyRoundIcon />
              )}
              保存并轮换
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  )
}

function ProfileForm({
  agent,
  connection,
}: {
  agent: NonNullable<ReturnType<typeof useAgentProfile>["data"]>
  connection: NonNullable<ReturnType<typeof useModelConnection>["data"]>
}) {
  const currentConnection = connection.current_revision
  const base = agent.draft?.config
  const [form, setForm] = useState<AgentConfig>(() => ({
    business_role: base?.business_role ?? "",
    business_instructions: base?.business_instructions ?? "",
    model_policy: {
      runtime: "claude_agent_sdk",
      model: currentConnection?.config.model ?? base?.model_policy.model ?? "",
      model_connection_revision_id: currentConnection?.id ?? "",
    },
    execution: base?.execution ?? { max_turns: 12, timeout_seconds: 300 },
    tools: base?.tools ?? [],
    skills: base?.skills ?? [],
    routing: base?.routing ?? { project_code: agent.definition.project_code },
    channels: base?.channels ?? { ingress: [], delivery: [] },
  }))
  const save = useSaveAgentDraft()
  const validate = useValidateAgentDraft()
  const publish = usePublishAgentDraft()

  function toggleList(field: "tools" | "skills", value: string) {
    setForm((current) => ({
      ...current,
      [field]: current[field].includes(value)
        ? current[field].filter((item) => item !== value)
        : [...current[field], value],
    }))
  }

  function toggleConnector(
    direction: "ingress" | "delivery",
    connectorId: string
  ) {
    setForm((current) => {
      const existing = current.channels[direction]
      return {
        ...current,
        channels: {
          ...current.channels,
          [direction]: existing.includes(connectorId)
            ? existing.filter((item) => item !== connectorId)
            : [...existing, connectorId],
        },
      }
    })
  }

  async function saveDraft() {
    try {
      const revision = await save.mutateAsync({
        expectedRevision: agent.draft?.revision ?? 0,
        config: form,
      })
      toast.success(`Agent 草稿 r${revision.revision} 已保存`)
    } catch {
      // Structured error is rendered below.
    }
  }

  const validationErrors = agent.draft?.validation.errors ?? []
  const draftPublished = agent.draft?.status === "published"
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>Agent 配置草稿</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="业务角色" htmlFor="profile-role">
              <Input
                id="profile-role"
                value={form.business_role}
                onChange={(event) =>
                  setForm({ ...form, business_role: event.target.value })
                }
              />
            </Field>
            <Field label="项目编码" htmlFor="profile-project">
              <Input
                id="profile-project"
                value={form.routing.project_code}
                onChange={(event) =>
                  setForm({
                    ...form,
                    routing: { project_code: event.target.value },
                  })
                }
              />
            </Field>
          </div>
          <Field label="业务指令" htmlFor="profile-instructions">
            <textarea
              id="profile-instructions"
              className={textareaClass}
              rows={7}
              value={form.business_instructions}
              onChange={(event) =>
                setForm({ ...form, business_instructions: event.target.value })
              }
            />
          </Field>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="最大轮次" htmlFor="profile-turns">
              <Input
                id="profile-turns"
                type="number"
                min={1}
                max={100}
                value={form.execution.max_turns}
                onChange={(event) =>
                  setForm({
                    ...form,
                    execution: {
                      ...form.execution,
                      max_turns: Number(event.target.value),
                    },
                  })
                }
              />
            </Field>
            <Field label="超时秒数" htmlFor="profile-timeout">
              <Input
                id="profile-timeout"
                type="number"
                min={10}
                max={3600}
                value={form.execution.timeout_seconds}
                onChange={(event) =>
                  setForm({
                    ...form,
                    execution: {
                      ...form.execution,
                      timeout_seconds: Number(event.target.value),
                    },
                  })
                }
              />
            </Field>
          </div>
          <ReadOnlyModelSummary connection={connection} />
          <Checklist
            title="只读工具"
            items={agent.catalog.tools}
            selected={form.tools}
            onToggle={(value) => toggleList("tools", value)}
          />
          <Checklist
            title="技能"
            items={agent.catalog.skills}
            selected={form.skills}
            onToggle={(value) => toggleList("skills", value)}
          />
          <div className="grid gap-4 lg:grid-cols-2">
            <Checklist
              title="入口 Connector"
              items={agent.catalog.connectors
                .filter((item) => Boolean(item.allow_ingress))
                .map((item) => item.id)}
              selected={form.channels.ingress}
              onToggle={(value) => toggleConnector("ingress", value)}
            />
            <Checklist
              title="投递 Connector"
              items={agent.catalog.connectors
                .filter((item) => Boolean(item.allow_delivery))
                .map((item) => item.id)}
              selected={form.channels.delivery}
              onToggle={(value) => toggleConnector("delivery", value)}
            />
          </div>
          <MutationMessage
            error={save.error ?? validate.error ?? publish.error}
          />
          {validationErrors.length ? (
            <ul className="space-y-1 rounded-lg border border-destructive/40 p-4 text-sm text-destructive">
              {validationErrors.map((error) => (
                <li key={`${error.field}:${error.message}`}>
                  {error.field}: {error.message}
                </li>
              ))}
            </ul>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              onClick={() => void saveDraft()}
              disabled={save.isPending || !currentConnection}
            >
              {save.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <SaveIcon />
              )}
              保存草稿
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!agent.draft || draftPublished || validate.isPending}
              onClick={() => agent.draft && validate.mutate(agent.draft.id)}
            >
              <CheckCircle2Icon />
              校验当前草稿
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={
                !agent.draft ||
                draftPublished ||
                !agent.draft.validation.valid ||
                publish.isPending ||
                !agent.permissions.can_publish
              }
              onClick={() => agent.draft && publish.mutate(agent.draft.id)}
            >
              <SendIcon />
              {draftPublished ? "当前版本已发布" : "发布 Agent"}
            </Button>
          </div>
          {draftPublished ? (
            <p className="text-xs text-muted-foreground">
              当前修订版本已经发布。修改配置并保存后会生成新的草稿版本。
            </p>
          ) : null}
          {!agent.permissions.can_publish ? (
            <p className="text-xs text-muted-foreground">
              当前账号可编辑草稿，但没有 Agent 发布或回滚权限。
            </p>
          ) : null}
        </CardContent>
      </Card>

      <div className="space-y-5">
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>当前有效发布版本</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {agent.current_publication ? (
              <>
                <StatusLine
                  label="发布版本"
                  value={agent.current_publication.id}
                  mono
                />
                <StatusLine
                  label="修订版本"
                  value={`r${agent.current_publication.revision}`}
                />
                <StatusLine
                  label="模型模式"
                  value={
                    "model_connection" in agent.current_publication.snapshot
                      ? "固定模型连接版本"
                      : "旧版全局连接"
                  }
                />
                <StatusLine
                  label="配置哈希"
                  value={`${agent.current_publication.config_hash.slice(0, 14)}…`}
                  mono
                />
              </>
            ) : (
              <p className="text-muted-foreground">尚未发布。</p>
            )}
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>发布规则</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>草稿校验通过后才能发布。</p>
            <p>新发布版本会固定模型连接版本与配置哈希。</p>
            <p>API Key 轮换会更新活动凭据，不会复制到发布版本。</p>
            <p>业务应用不会自动切换到新的 Agent 发布版本。</p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function PublicationHistory({
  currentId,
  canPublish,
}: {
  currentId: string
  canPublish: boolean
}) {
  const publications = useAgentPublications()
  const rollback = useRollbackAgentPublication()
  if (publications.isLoading) return <Skeleton className="h-80 w-full" />
  if (publications.isError || !publications.data) {
    return <MutationMessage error={publications.error} />
  }
  return (
    <div className="space-y-4">
      {publications.data.map((publication) => {
        const current = publication.id === currentId
        return (
          <Card key={publication.id} className="shadow-none">
            <CardContent className="grid gap-4 py-5 lg:grid-cols-[minmax(0,1fr)_auto]">
              <div className="min-w-0 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={current ? "default" : "outline"}>
                    r{publication.revision}
                  </Badge>
                  {current ? <Badge variant="secondary">当前版本</Badge> : null}
                  <Badge variant="outline">
                    {publication.model_runtime_mode === "pinned_connection"
                      ? "固定模型连接"
                      : "旧版全局连接"}
                  </Badge>
                </div>
                <p className="font-mono text-xs break-all">{publication.id}</p>
                <p className="text-xs text-muted-foreground">
                  {new Date(publication.published_at).toLocaleString()} · hash{" "}
                  {publication.config_hash.slice(0, 16)}…
                </p>
                <div className="rounded-lg bg-muted/50 p-3 text-sm">
                  <p className="font-medium">仍使用此版本的激活应用</p>
                  {publication.active_applications?.length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {publication.active_applications.map((application) => (
                        <Link
                          key={application.code}
                          to={application.href}
                          className="rounded-md border bg-background px-2.5 py-1 text-xs hover:bg-accent"
                        >
                          {application.name} · {application.environment}
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-1 text-xs text-muted-foreground">
                      没有激活应用固定到此版本。
                    </p>
                  )}
                </div>
              </div>
              <Button
                variant="outline"
                disabled={current || rollback.isPending || !canPublish}
                onClick={() => rollback.mutate(publication.id)}
              >
                <RotateCcwIcon />
                回退 Agent
              </Button>
            </CardContent>
          </Card>
        )
      })}
      <MutationMessage error={rollback.error} />
    </div>
  )
}

function ReadOnlyModelSummary({
  connection,
}: {
  connection: NonNullable<ReturnType<typeof useModelConnection>["data"]>
}) {
  const revision = connection.current_revision
  return (
    <div className="rounded-lg border bg-muted/20 p-4">
      <p className="font-medium">模型策略</p>
      <p className="mt-1 text-sm text-muted-foreground">
        {revision
          ? `${revision.config.model} · ${revision.provider_host} · 连接 r${revision.revision}`
          : "模型连接未配置"}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        URL、Key、默认模型映射和 effort level 请在“模型连接”页签修改。
      </p>
    </div>
  )
}

function modelConnectionStatusLabel(status: string): string {
  return (
    {
      ready: "已就绪",
      rotation_required: "需要轮换凭据",
      missing_revision: "引用版本已删除，请重新配置",
      disabled: "已停用",
      legacy_global_connection: "旧版全局连接",
      unconfigured: "未配置",
    }[status] ?? status
  )
}

function Checklist({
  title,
  items,
  selected,
  onToggle,
}: {
  title: string
  items: string[]
  selected: string[]
  onToggle: (value: string) => void
}) {
  return (
    <fieldset className="rounded-lg border p-4">
      <legend className="px-1 text-sm font-medium">{title}</legend>
      {items.length ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {items.map((item) => (
            <label
              key={item}
              className="flex min-w-0 items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                checked={selected.includes(item)}
                onChange={() => onToggle(item)}
              />
              <span className="truncate font-mono text-xs">{item}</span>
            </label>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">目录为空。</p>
      )}
    </fieldset>
  )
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  )
}

function StatusLine({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="grid grid-cols-[7rem_minmax(0,1fr)] gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className={mono ? "font-mono text-xs break-all" : "break-words"}>
        {value}
      </span>
    </div>
  )
}

function MutationMessage({ error }: { error: unknown }) {
  if (!error) return null
  if (error instanceof ApiError) {
    return (
      <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        <p>{error.message}</p>
        {error.fieldErrors.map((item) => (
          <p key={`${item.field}:${item.message}`} className="mt-1 text-xs">
            {item.field}: {item.message}
          </p>
        ))}
      </div>
    )
  }
  return (
    <p className="text-sm text-destructive">操作失败，请稍后重试。</p>
  )
}

const selectClass =
  "border-input bg-transparent shadow-xs focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-3 text-sm outline-none focus-visible:ring-[3px]"
const textareaClass =
  "border-input bg-transparent shadow-xs focus-visible:border-ring focus-visible:ring-ring/50 w-full rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-[3px]"
