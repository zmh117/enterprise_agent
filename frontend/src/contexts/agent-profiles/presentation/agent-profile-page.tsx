import { useEffect, useState, type FormEvent } from "react"
import {
  BotIcon,
  CheckCircle2Icon,
  FlaskConicalIcon,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  useAgentProfile,
  useAgentProfiles,
  useAgentPublications,
  useConfigureConnection,
  useDiscoverConnection,
  useModelConnection,
  usePublishAgentDraft,
  useRollbackAgentPublication,
  useSaveAgentDraft,
  useTestDraftConnection,
  useValidateAgentDraft,
} from "@/contexts/agent-profiles/application/agent-profile-queries"
import type {
  AgentConfig,
  AgentDetail,
  CredentialSource,
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
                    profile.model_connection_status
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
      key={`${agent.data.draft?.revision ?? 0}`}
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
          发布版本，不会自动切换任何业务应用。已激活应用仍使用它自己固定的 Agent
          发布版本，需进入应用详情手动更新并重新发布。
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

type ConnectionWizardPhase =
  "EDITING" | "DISCOVERED" | "MAPPED" | "TESTED" | "READY"

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
  const existingCredentialAvailable = Boolean(
    current?.credential.configured &&
    !current.credential.rotation_required &&
    current.status === "ready"
  )
  const allowed = canManageCredential && canTestConnection
  const discover = useDiscoverConnection()
  const testDraft = useTestDraftConnection()
  const configure = useConfigureConnection()
  const [phase, setPhase] = useState<ConnectionWizardPhase>("EDITING")
  const [credentialSource, setCredentialSource] = useState<CredentialSource>(
    existingCredentialAvailable ? "existing" : "submitted"
  )
  const [apiKey, setApiKey] = useState("")
  const [error, setError] = useState<unknown>(null)
  const [discovery, setDiscovery] = useState<Awaited<
    ReturnType<typeof discover.mutateAsync>
  > | null>(null)
  const [testResult, setTestResult] = useState<Awaited<
    ReturnType<typeof testDraft.mutateAsync>
  > | null>(null)
  const [form, setForm] = useState<
    Omit<ModelConnectionConfig, "schema_version">
  >({
    protocol: "anthropic_compatible",
    base_url: current?.config.base_url ?? "https://api.deepseek.com/anthropic",
    model: current?.config.model ?? "",
    default_opus_model: current?.config.default_opus_model ?? "",
    default_sonnet_model: current?.config.default_sonnet_model ?? "",
    default_haiku_model: current?.config.default_haiku_model ?? "",
    subagent_model: current?.config.subagent_model ?? "",
    effort_level: current?.config.effort_level ?? "max",
  })

  useEffect(
    () => () => {
      discover.reset()
      testDraft.reset()
      configure.reset()
    },
    // Mutation objects are stable for the lifetime of this wizard.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  )

  const modelIds = new Set(discovery?.models.map((item) => item.id) ?? [])
  const legacyModels = discovery
    ? Array.from(
        new Set(
          [
            current?.config.model,
            current?.config.default_opus_model,
            current?.config.default_sonnet_model,
            current?.config.default_haiku_model,
            current?.config.subagent_model,
          ].filter((value): value is string =>
            Boolean(value && !modelIds.has(value))
          )
        )
      )
    : []

  function credentialInput() {
    return {
      credential_source: credentialSource,
      api_key: credentialSource === "submitted" ? apiKey : "",
    }
  }

  function invalidateDiscovery({ clearKey = true } = {}) {
    setDiscovery(null)
    setTestResult(null)
    setPhase("EDITING")
    setError(null)
    discover.reset()
    testDraft.reset()
    configure.reset()
    if (clearKey) setApiKey("")
  }

  function invalidateTest(nextForm: typeof form) {
    setForm(nextForm)
    setTestResult(null)
    setPhase(nextForm.model ? "MAPPED" : "DISCOVERED")
    setError(null)
    testDraft.reset()
    configure.reset()
  }

  async function runDiscovery() {
    setError(null)
    try {
      const result = await discover.mutateAsync({
        ...credentialInput(),
        base_url: form.base_url,
        timeout_seconds: 15,
      })
      setDiscovery(result)
      setTestResult(null)
      const available = new Set(result.models.map((item) => item.id))
      setForm((value) => {
        return {
          ...value,
          base_url: result.normalized_base_url,
          model: available.has(value.model) ? value.model : "",
          default_opus_model: available.has(value.default_opus_model)
            ? value.default_opus_model
            : "",
          default_sonnet_model: available.has(value.default_sonnet_model)
            ? value.default_sonnet_model
            : "",
          default_haiku_model: available.has(value.default_haiku_model)
            ? value.default_haiku_model
            : "",
          subagent_model: available.has(value.subagent_model)
            ? value.subagent_model
            : "",
        }
      })
      setPhase(available.has(form.model) ? "MAPPED" : "DISCOVERED")
    } catch (caught) {
      setError(caught)
      setDiscovery(null)
      setTestResult(null)
      setPhase("EDITING")
    } finally {
      discover.reset()
    }
  }

  async function runTest() {
    setError(null)
    try {
      const result = await testDraft.mutateAsync({
        ...credentialInput(),
        config: form,
        timeout_seconds: 15,
      })
      setTestResult(result)
      setPhase("TESTED")
    } catch (caught) {
      setError(caught)
      setTestResult(null)
      setPhase("MAPPED")
    } finally {
      testDraft.reset()
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const revision = await configure.mutateAsync({
        expected_revision: connection.revision,
        ...credentialInput(),
        config: form,
        timeout_seconds: 15,
      })
      setApiKey("")
      setPhase("READY")
      toast.success(`模型连接 r${revision.revision} 已就绪`)
    } catch (caught) {
      setError(caught)
      setApiKey("")
      setDiscovery(null)
      setTestResult(null)
      setPhase("EDITING")
      if (caught instanceof ApiError && caught.code === "revision_conflict") {
        toast.error("连接已被其他操作更新，请重新发现并测试")
      }
    } finally {
      configure.reset()
    }
  }

  return (
    <form
      onSubmit={submit}
      className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]"
    >
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>DeepSeek 模型连接向导</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-2 sm:grid-cols-5">
            {(
              [
                ["EDITING", "1 地址与 Key"],
                ["DISCOVERED", "2 模型发现"],
                ["MAPPED", "3 模型映射"],
                ["TESTED", "4 配置测试"],
                ["READY", "5 已保存"],
              ] as const
            ).map(([value, label]) => (
              <Badge
                key={value}
                variant={phase === value ? "default" : "outline"}
                className="justify-center py-1.5"
              >
                {label}
              </Badge>
            ))}
          </div>

          <section className="space-y-4">
            <div>
              <h3 className="font-medium">1. 地址与 Credential</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                仅支持 DeepSeek 官方 HTTPS Anthropic 地址。API Key
                只保存在当前页面内存，保存后立即清空。
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="服务地址（Base URL）" htmlFor="model-base-url">
                <Input
                  id="model-base-url"
                  value={form.base_url}
                  onChange={(event) => {
                    setForm((value) => ({
                      ...value,
                      base_url: event.target.value,
                    }))
                    invalidateDiscovery()
                  }}
                  placeholder="https://api.deepseek.com/anthropic"
                  disabled={!allowed}
                  required
                />
              </Field>
              <Field label="Credential 来源" htmlFor="credential-source">
                <select
                  id="credential-source"
                  className={selectClass}
                  value={credentialSource}
                  disabled={!allowed}
                  onChange={(event) => {
                    setCredentialSource(event.target.value as CredentialSource)
                    invalidateDiscovery()
                  }}
                >
                  <option value="submitted">使用新的 API Key</option>
                  <option
                    value="existing"
                    disabled={!existingCredentialAvailable}
                  >
                    沿用当前有效 Credential
                  </option>
                </select>
              </Field>
              {credentialSource === "submitted" ? (
                <Field label="新的 API Key" htmlFor="model-api-key">
                  <Input
                    id="model-api-key"
                    type="password"
                    autoComplete="new-password"
                    value={apiKey}
                    onChange={(event) => {
                      setApiKey(event.target.value)
                      invalidateDiscovery({ clearKey: false })
                    }}
                    placeholder="输入 DeepSeek API Key"
                    disabled={!allowed}
                    required
                  />
                </Field>
              ) : (
                <div className="rounded-md border bg-muted/30 p-3 text-sm">
                  <p className="font-medium">沿用加密 Credential</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {current?.credential.masked} · v
                    {current?.credential.version}
                  </p>
                </div>
              )}
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={() => void runDiscovery()}
              disabled={
                !allowed ||
                discover.isPending ||
                !form.base_url ||
                (credentialSource === "submitted" && !apiKey)
              }
            >
              {discover.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <FlaskConicalIcon />
              )}
              发现可用模型
            </Button>
          </section>

          {discovery ? (
            <section className="space-y-4 border-t pt-5">
              <div>
                <h3 className="font-medium">2–3. 选择模型映射</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  已从 {discovery.provider_host} 发现 {discovery.models.length}{" "}
                  个模型，耗时 {discovery.duration_ms}ms。
                </p>
              </div>
              {legacyModels.length ? (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                  历史模型已不可用：{legacyModels.join("、")}
                  。历史版本保持不变， 本次必须重新选择。
                </div>
              ) : null}
              <div className="grid gap-4 md:grid-cols-2">
                <ModelChoice
                  id="model-primary"
                  label="主模型"
                  value={form.model}
                  models={discovery.models}
                  required
                  onChange={(value) =>
                    invalidateTest({ ...form, model: value })
                  }
                />
                <ModelChoice
                  id="model-opus"
                  label="Opus 默认模型"
                  value={form.default_opus_model}
                  models={discovery.models}
                  onChange={(value) =>
                    invalidateTest({ ...form, default_opus_model: value })
                  }
                />
                <ModelChoice
                  id="model-sonnet"
                  label="Sonnet 默认模型"
                  value={form.default_sonnet_model}
                  models={discovery.models}
                  onChange={(value) =>
                    invalidateTest({ ...form, default_sonnet_model: value })
                  }
                />
                <ModelChoice
                  id="model-haiku"
                  label="Haiku 默认模型"
                  value={form.default_haiku_model}
                  models={discovery.models}
                  onChange={(value) =>
                    invalidateTest({ ...form, default_haiku_model: value })
                  }
                />
                <ModelChoice
                  id="model-subagent"
                  label="子 Agent 模型"
                  value={form.subagent_model}
                  models={discovery.models}
                  onChange={(value) =>
                    invalidateTest({ ...form, subagent_model: value })
                  }
                />
                <Field label="推理强度" htmlFor="model-effort">
                  <select
                    id="model-effort"
                    className={selectClass}
                    value={form.effort_level}
                    onChange={(event) =>
                      invalidateTest({
                        ...form,
                        effort_level: event.target
                          .value as typeof form.effort_level,
                      })
                    }
                  >
                    <option value="low">低</option>
                    <option value="medium">中</option>
                    <option value="high">高</option>
                    <option value="max">最高</option>
                  </select>
                </Field>
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={() => void runTest()}
                disabled={!allowed || testDraft.isPending || !form.model}
              >
                {testDraft.isPending ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <FlaskConicalIcon />
                )}
                测试当前配置
              </Button>
            </section>
          ) : null}

          {testResult ? (
            <section className="space-y-3 border-t pt-5">
              <h3 className="font-medium">4. 测试通过</h3>
              <p className="text-sm text-emerald-700">
                连接成功 · {testResult.provider_host} · {testResult.model} ·{" "}
                {testResult.duration_ms}ms
              </p>
              <p className="text-xs text-muted-foreground">
                最终保存会在服务端重新发现模型并再次执行最小 SDK 测试。
              </p>
            </section>
          ) : null}

          <MutationMessage error={error} />
          <Button
            type="submit"
            disabled={!allowed || phase !== "TESTED" || configure.isPending}
          >
            {configure.isPending ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <SaveIcon />
            )}
            验证并原子保存
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-5">
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>当前连接</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <StatusLine
              label="状态"
              value={
                existingCredentialAvailable ? "已就绪" : "需要新的 API Key"
              }
            />
            <StatusLine
              label="脱敏值"
              value={current?.credential.masked || "未保存"}
              mono
            />
            <StatusLine
              label="凭据版本"
              value={`v${current?.credential.version ?? 0}`}
            />
            <StatusLine label="连接版本" value={`r${connection.revision}`} />
            <StatusLine
              label="提供方主机"
              value={current?.provider_host || "未配置"}
              mono
            />
            {!allowed ? (
              <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
                当前账号需要 Agent 编辑和 Secret 管理权限才能配置模型连接。
              </p>
            ) : null}
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>安全边界</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>仅允许 DeepSeek 官方 HTTPS 地址与 443 端口。</p>
            <p>拒绝 URL 凭据、重定向、私网和环回 DNS 结果。</p>
            <p>发现与测试不保存 Key；最终配置才写入加密 Secret。</p>
            <p>保存连接不会自动发布 Agent 或切换业务应用。</p>
          </CardContent>
        </Card>
      </div>
    </form>
  )
}

function ModelChoice({
  id,
  label,
  value,
  models,
  required = false,
  onChange,
}: {
  id: string
  label: string
  value: string
  models: Array<{ id: string; display_name: string }>
  required?: boolean
  onChange: (value: string) => void
}) {
  return (
    <Field label={label} htmlFor={id}>
      <select
        id={id}
        className={selectClass}
        value={value}
        required={required}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{required ? "请选择模型" : "继承主模型"}</option>
        {models.map((model) => (
          <option key={model.id} value={model.id}>
            {model.display_name}
          </option>
        ))}
      </select>
    </Field>
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
  const persistedForm: AgentConfig = {
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
    api_capability_release_ids: base?.api_capability_release_ids ?? [],
  }
  const [form, setForm] = useState<AgentConfig>(() => persistedForm)
  const save = useSaveAgentDraft()
  const validate = useValidateAgentDraft()
  const publish = usePublishAgentDraft()
  const draftDirty = JSON.stringify(form) !== JSON.stringify(persistedForm)

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

  const validationErrors = draftDirty
    ? []
    : (agent.draft?.validation.errors ?? [])
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
          <AgentCapabilitySelector
            releases={agent.catalog.api_capabilities}
            selected={form.api_capability_release_ids}
            onChange={(api_capability_release_ids) =>
              setForm({ ...form, api_capability_release_ids })
            }
          />
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
            <ConnectorChecklist
              title="入口 Connector"
              direction="ingress"
              connectors={agent.catalog.connectors}
              selected={form.channels.ingress}
              onToggle={(value) => toggleConnector("ingress", value)}
            />
            <ConnectorChecklist
              title="投递 Connector"
              direction="delivery"
              connectors={agent.catalog.connectors}
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
          {draftDirty ? (
            <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              当前修改尚未保存，请先保存草稿，再校验和发布。
            </p>
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
              disabled={
                !agent.draft ||
                draftPublished ||
                draftDirty ||
                validate.isPending
              }
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
                draftDirty ||
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

function AgentCapabilitySelector({
  releases,
  selected,
  onChange,
}: {
  releases: Array<{
    id: string
    identifier: string
    release_revision: number
    name: string
    description: string
    status: string
    release_note: string
  }>
  selected: string[]
  onChange: (value: string[]) => void
}) {
  const identifiers = new Set(releases.map((item) => item.identifier))
  return (
    <fieldset className="rounded-lg border p-4">
      <legend className="px-1 text-sm font-medium">
        API Capability Release
      </legend>
      <p className="mb-3 text-xs leading-5 text-muted-foreground">
        每个 Identifier 最多选择一个精确 ACTIVE Release。description
        会进入模型 Tool 定义；Release Note 仅供管理员判断版本。
      </p>
      <div className="space-y-2">
        {releases.map((release) => {
          const checked = selected.includes(release.id)
          const sameIdentifierSelected = releases.some(
            (candidate) =>
              candidate.identifier === release.identifier &&
              selected.includes(candidate.id) &&
              candidate.id !== release.id,
          )
          return (
            <label
              key={release.id}
              className="flex items-start gap-3 rounded-lg border p-3 text-sm"
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={release.status !== "ACTIVE"}
                onChange={() => {
                  const withoutIdentifier = selected.filter(
                    (id) =>
                      !releases.some(
                        (candidate) =>
                          candidate.id === id &&
                          candidate.identifier === release.identifier,
                      ),
                  )
                  onChange(checked ? withoutIdentifier : [...withoutIdentifier, release.id])
                }}
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2 font-medium">
                  {release.name}
                  <Badge variant="outline">
                    r{release.release_revision} · {release.status}
                  </Badge>
                </span>
                <span className="mt-1 block font-mono text-xs text-indigo-700">
                  {release.identifier}
                </span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                  {release.description}
                </span>
                {release.release_note ? (
                  <span className="mt-1 block text-xs text-muted-foreground">
                    发布备注：{release.release_note}
                  </span>
                ) : null}
                {sameIdentifierSelected ? (
                  <span className="mt-1 block text-xs text-amber-700">
                    选择此版本会替换同 Identifier 的当前版本。
                  </span>
                ) : null}
              </span>
            </label>
          )
        })}
        {releases.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            当前没有可供新 Agent 发布选择的 ACTIVE Capability Release。
          </p>
        ) : null}
        {selected
          .filter((id) => !releases.some((item) => item.id === id))
          .map((id) => (
            <div
              key={id}
              className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900"
            >
              历史精确 Release {id} 不在 ACTIVE 目录中；请移除或显式替换后再发布。
            </div>
          ))}
      </div>
      <span className="sr-only">目录 Identifier 数量 {identifiers.size}</span>
    </fieldset>
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

function ConnectorChecklist({
  title,
  direction,
  connectors,
  selected,
  onToggle,
}: {
  title: string
  direction: "ingress" | "delivery"
  connectors: AgentDetail["catalog"]["connectors"]
  selected: string[]
  onToggle: (value: string) => void
}) {
  const available = connectors.filter((connector) =>
    Boolean(
      direction === "ingress"
        ? connector.allow_ingress
        : connector.allow_delivery,
    ),
  )
  const availableIds = new Set(available.map((connector) => connector.id))
  const unavailableSelected = selected.filter((id) => !availableIds.has(id))

  return (
    <fieldset className="rounded-lg border p-4">
      <legend className="px-1 text-sm font-medium">{title}</legend>
      {available.length || unavailableSelected.length ? (
        <div className="grid gap-3">
          {available.map((connector) => (
            <label
              key={connector.id}
              className="flex min-w-0 items-start gap-2 text-sm"
            >
              <input
                className="mt-0.5"
                type="checkbox"
                checked={selected.includes(connector.id)}
                onChange={() => onToggle(connector.id)}
              />
              <span className="min-w-0">
                <span className="block font-medium">{connector.name}</span>
                <span className="block truncate font-mono text-xs text-muted-foreground">
                  {connector.id}
                </span>
              </span>
            </label>
          ))}
          {unavailableSelected.map((connectorId) => (
            <label
              key={connectorId}
              className="flex min-w-0 items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-2 text-sm"
            >
              <input
                className="mt-0.5"
                type="checkbox"
                checked
                onChange={() => onToggle(connectorId)}
              />
              <span className="min-w-0">
                <span className="block break-all font-mono text-xs">
                  {connectorId}
                </span>
                <span className="mt-1 block text-xs text-destructive">
                  Connector 已停用或删除，请取消选择后保存草稿。
                </span>
              </span>
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
  return <p className="text-sm text-destructive">操作失败，请稍后重试。</p>
}

const selectClass =
  "border-input bg-transparent shadow-xs focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full rounded-md border px-3 text-sm outline-none focus-visible:ring-[3px]"
const textareaClass =
  "border-input bg-transparent shadow-xs focus-visible:border-ring focus-visible:ring-ring/50 w-full rounded-md border px-3 py-2 text-sm outline-none focus-visible:ring-[3px]"
