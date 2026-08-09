import { useState, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeftIcon,
  BotIcon,
  PlusIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SaveIcon,
  SendIcon,
  ShieldCheckIcon,
} from "lucide-react"
import { Link, useNavigate, useParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  agentKeys,
  useAgent,
  useAgentActions,
  useAgentPublications,
  useAgents,
  useModelConnection,
  useModelConnectionActions,
} from "@/contexts/agents/application/agent-queries"
import type {
  AgentDetail,
  AgentDraftConfig,
} from "@/contexts/agents/domain/agent"
import { createAgent } from "@/contexts/agents/infrastructure/agent-api"
import {
  ManagementError,
  ManagementLoading,
  ManagementPage,
  MutationNotice,
} from "@/shared/presentation/management-states"

export function AgentListPage() {
  const query = useAgents()
  const [creating, setCreating] = useState(false)
  return (
    <ManagementPage>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-indigo-700">
            Agent Control Plane
          </p>
          <h1 className="mt-1 text-2xl font-semibold">Agent Publication</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            管理多个 Agent 的草稿、固定 Runtime 发布版本和业务应用引用。
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
          >
            <RefreshCwIcon className={query.isFetching ? "animate-spin" : ""} />
            刷新
          </Button>
          {query.data?.permissions.can_create ? (
            <Button
              type="button"
              onClick={() => setCreating((value) => !value)}
            >
              <PlusIcon />
              新建 Agent
            </Button>
          ) : null}
        </div>
      </header>
      {creating ? <CreateAgentForm onClose={() => setCreating(false)} /> : null}
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error} retry={() => void query.refetch()} />
      {query.data && query.data.agents.length === 0 ? (
        <Card className="shadow-none">
          <CardContent className="p-10 text-center">
            <BotIcon className="mx-auto size-8 text-muted-foreground" />
            <p className="mt-3 font-medium">暂无可查看的 Agent</p>
            <p className="mt-1 text-sm text-muted-foreground">
              创建权限与项目授权由后端统一控制。
            </p>
          </CardContent>
        </Card>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {query.data?.agents.map((agent) => (
          <Card key={agent.code} className="shadow-none">
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle>
                  <Link
                    className="hover:underline"
                    to={`/agent-profiles/${encodeURIComponent(agent.code)}`}
                  >
                    {agent.name}
                  </Link>
                </CardTitle>
                <Badge
                  variant={agent.status === "enabled" ? "secondary" : "outline"}
                >
                  {lifecycleLabel(agent.status)}
                </Badge>
              </div>
              <p className="font-mono text-xs text-muted-foreground">
                {agent.code} · {agent.project_code}
              </p>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
              <Summary
                label="当前发布"
                value={
                  agent.current_publication
                    ? `r${agent.current_publication.revision}`
                    : "未发布"
                }
              />
              <Summary
                label="模型状态"
                value={agent.model_connection_status || "未绑定"}
              />
              <Summary
                label="活动应用"
                value={`${agent.active_application_count ?? 0} 个`}
              />
            </CardContent>
          </Card>
        ))}
      </div>
    </ManagementPage>
  )
}

function CreateAgentForm({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const mutation = useMutation({
    mutationFn: createAgent,
    onSuccess: async (agent) => {
      await client.invalidateQueries({ queryKey: agentKeys.all })
      navigate(`/agent-profiles/${encodeURIComponent(agent.definition.code)}`)
    },
  })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    mutation.mutate({
      code: String(form.get("code") || ""),
      name: String(form.get("name") || ""),
      description: String(form.get("description") || ""),
      project_code: String(form.get("project_code") || ""),
    })
  }
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>新建 Agent</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
          <Field label="代码" name="code" required />
          <Field label="名称" name="name" required />
          <Field label="项目代码" name="project_code" required />
          <Field label="说明" name="description" />
          <div className="sm:col-span-2">
            <MutationNotice error={mutation.error} />
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" disabled={mutation.isPending}>
              创建
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>
              取消
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

export function AgentDetailPage() {
  const code = useParams().agentCode ?? ""
  const query = useAgent(code)
  const publications = useAgentPublications(code)
  if (query.isLoading)
    return (
      <ManagementPage>
        <ManagementLoading />
      </ManagementPage>
    )
  if (query.isError || !query.data)
    return (
      <ManagementPage>
        <Back to="/agent-profiles" />
        <ManagementError
          error={query.error}
          retry={() => void query.refetch()}
        />
      </ManagementPage>
    )
  return (
    <AgentEditor
      key={`${query.data.definition.revision}:${query.data.draft?.id ?? "none"}`}
      detail={query.data}
      publications={publications.data ?? []}
      publicationsError={publications.error}
      refreshPublications={() => void publications.refetch()}
    />
  )
}

function AgentEditor({
  detail,
  publications,
  publicationsError,
  refreshPublications,
}: {
  detail: AgentDetail
  publications: Array<{
    id: string
    revision: number
    config_hash: string
    created_at?: string
    created_by?: string
  }>
  publicationsError: unknown
  refreshPublications: () => void
}) {
  const code = detail.definition.code
  const actions = useAgentActions(code)
  const initial = detail.draft?.config ?? defaultConfig(detail)
  const [config, setConfig] = useState<AgentDraftConfig>(initial)
  const [selectedSkills, setSelectedSkills] = useState(new Set(initial.skills))
  const [selectedTools, setSelectedTools] = useState(
    new Set(initial.mcp_tool_publication_ids)
  )
  const [metadata, setMetadata] = useState({
    name: detail.definition.name,
    description: detail.definition.description,
    project_code: detail.definition.project_code,
    status: detail.definition.status,
  })
  const mutable =
    detail.permissions.can_edit && detail.management_mode === "editable"
  const updateConfig = () => ({
    ...config,
    skills: Array.from(selectedSkills),
    mcp_tool_publication_ids: Array.from(selectedTools),
  })
  const error =
    actions.update.error ||
    actions.saveDraft.error ||
    actions.validate.error ||
    actions.publish.error ||
    actions.rollback.error
  return (
    <ManagementPage>
      <Back to="/agent-profiles" />
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold">{detail.definition.name}</h1>
            <Badge
              variant={
                detail.definition.status === "enabled" ? "secondary" : "outline"
              }
            >
              {lifecycleLabel(detail.definition.status)}
            </Badge>
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {code} · definition r{detail.definition.revision}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={!mutable || !detail.draft || actions.validate.isPending}
            onClick={() =>
              detail.draft &&
              actions.validate.mutate({
                revisionId: detail.draft.id,
                expectedRevision: detail.definition.revision,
              })
            }
          >
            <ShieldCheckIcon />
            校验
          </Button>
          <Button
            type="button"
            disabled={
              !detail.permissions.can_publish ||
              !detail.draft ||
              actions.publish.isPending
            }
            onClick={() =>
              detail.draft &&
              actions.publish.mutate({
                revisionId: detail.draft.id,
                expectedRevision: detail.definition.revision,
              })
            }
          >
            <SendIcon />
            发布
          </Button>
        </div>
      </header>
      <MutationNotice error={error} />
      {detail.current_publication ? (
        <Card className="shadow-none">
          <CardContent className="grid gap-3 p-4 text-sm sm:grid-cols-4">
            <Summary
              label="当前 Publication"
              value={`r${detail.current_publication.revision}`}
            />
            <Summary
              label="Config hash"
              value={shortHash(detail.current_publication.config_hash)}
            />
            <Summary
              label="Runtime"
              value={runtimeFrom(detail.current_publication.snapshot)}
            />
            <Summary
              label="活动应用"
              value={`${detail.current_publication.active_applications?.length ?? 0} 个`}
            />
          </CardContent>
        </Card>
      ) : null}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(20rem,1fr)]">
        <div className="space-y-5">
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>定义与生命周期</CardTitle>
              <p className="text-sm text-muted-foreground">
                归档前必须先停用，且不能存在活动 Application 引用。
              </p>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <TextField
                label="名称"
                value={metadata.name}
                disabled={!detail.permissions.can_edit}
                onChange={(value) => setMetadata({ ...metadata, name: value })}
              />
              <TextField
                label="项目代码"
                value={metadata.project_code}
                disabled={!detail.permissions.can_edit}
                onChange={(value) =>
                  setMetadata({ ...metadata, project_code: value })
                }
              />
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="agent-description">说明</Label>
                <Textarea
                  id="agent-description"
                  value={metadata.description}
                  disabled={!detail.permissions.can_edit}
                  onChange={(event) =>
                    setMetadata({
                      ...metadata,
                      description: event.target.value,
                    })
                  }
                />
              </div>
              <NativeSelect
                label="生命周期"
                value={metadata.status}
                disabled={!detail.permissions.can_edit}
                options={lifecycleOptions(detail.definition.status)}
                onChange={(value) =>
                  setMetadata({
                    ...metadata,
                    status: value as typeof metadata.status,
                  })
                }
              />
              <div className="flex items-end">
                <Button
                  type="button"
                  variant="outline"
                  disabled={
                    !detail.permissions.can_edit || actions.update.isPending
                  }
                  onClick={() =>
                    actions.update.mutate({
                      expectedRevision: detail.definition.revision,
                      ...metadata,
                    })
                  }
                >
                  <SaveIcon />
                  保存定义
                </Button>
              </div>
            </CardContent>
          </Card>
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>业务行为</CardTitle>
              <p className="text-sm text-muted-foreground">
                安全规则、系统 Prompt 和写 Tool 由平台强制，不在此处开放。
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <Label htmlFor="business-role">业务角色</Label>
              <Input
                id="business-role"
                value={config.business_role}
                disabled={!mutable}
                onChange={(event) =>
                  setConfig({ ...config, business_role: event.target.value })
                }
              />
              <Label htmlFor="business-instructions">业务指令</Label>
              <Textarea
                id="business-instructions"
                rows={8}
                value={config.business_instructions}
                disabled={!mutable}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    business_instructions: event.target.value,
                  })
                }
              />
            </CardContent>
          </Card>
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>模型与执行限制</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <NativeSelect
                label="模型连接版本"
                value={config.model_policy.model_connection_revision_id}
                disabled={!mutable}
                onChange={(value) =>
                  setConfig({
                    ...config,
                    model_policy: {
                      ...config.model_policy,
                      model_connection_revision_id: value,
                    },
                  })
                }
                options={detail.model_connections.flatMap((connection) =>
                  connection.current_revision_id
                    ? [
                        {
                          value: connection.current_revision_id,
                          label: `${connection.name ?? connection.code} · r${connection.revision}`,
                        },
                      ]
                    : []
                )}
              />
              <NativeSelect
                label="模型"
                value={config.model_policy.model}
                disabled={!mutable}
                onChange={(value) =>
                  setConfig({
                    ...config,
                    model_policy: { ...config.model_policy, model: value },
                  })
                }
                options={detail.catalog.models.map((value) => ({
                  value,
                  label: value,
                }))}
              />
              <NumberField
                label="最大轮次"
                value={config.execution.max_turns}
                min={1}
                max={100}
                disabled={!mutable}
                onChange={(value) =>
                  setConfig({
                    ...config,
                    execution: { ...config.execution, max_turns: value },
                  })
                }
              />
              <NumberField
                label="超时（秒）"
                value={config.execution.timeout_seconds}
                min={10}
                max={3600}
                disabled={!mutable}
                onChange={(value) =>
                  setConfig({
                    ...config,
                    execution: { ...config.execution, timeout_seconds: value },
                  })
                }
              />
            </CardContent>
          </Card>
          <ChoiceCard
            title="Skills"
            help="仅发布代码仓库已注册的 Skill。"
            options={detail.catalog.skills.map((value) => ({
              id: value,
              label: value,
              description: "代码发布能力",
            }))}
            selected={selectedSkills}
            disabled={!mutable}
            onToggle={(id, checked) =>
              setSelectedSkills(toggleSet(selectedSkills, id, checked))
            }
          />
          <ChoiceCard
            title="MCP Tool 最大集合"
            help="Application 只能从此不可变集合中继续取子集。"
            options={detail.catalog.mcp_tools.map((tool) => ({
              id: tool.id,
              label: `${tool.server_code ?? "mcp"}.${tool.tool_name ?? tool.code ?? tool.id}`,
              description: `${tool.server_version ?? ""} · ${tool.resource_kind || "无 Resource"}${tool.resource_code ? `/${tool.resource_code}` : ""}`,
            }))}
            selected={selectedTools}
            disabled={!mutable}
            onToggle={(id, checked) =>
              setSelectedTools(toggleSet(selectedTools, id, checked))
            }
          />
          <div className="flex justify-end">
            <Button
              type="button"
              disabled={!mutable || actions.saveDraft.isPending}
              onClick={() =>
                actions.saveDraft.mutate({
                  expectedRevision: detail.draft?.revision ?? 0,
                  config: updateConfig(),
                })
              }
            >
              <SaveIcon />
              保存新草稿
            </Button>
          </div>
        </div>
        <aside className="space-y-5">
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>模型连接</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {detail.model_connections.map((connection) => (
                <div key={connection.code} className="rounded-lg border p-3">
                  <div className="flex justify-between gap-2">
                    <span className="font-medium">
                      {connection.name ?? connection.code}
                    </span>
                    <Badge
                      variant={
                        connection.status === "enabled"
                          ? "secondary"
                          : "outline"
                      }
                    >
                      {connection.status === "enabled" ? "已启用" : "已停用"}
                    </Badge>
                  </div>
                  <Link
                    className="mt-2 inline-block text-sm text-indigo-700 hover:underline"
                    to={`/agent-profiles/${encodeURIComponent(code)}/model-connections/${encodeURIComponent(connection.code)}`}
                  >
                    配置状态与测试
                  </Link>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>Publication 历史</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <ManagementError
                error={publicationsError}
                retry={refreshPublications}
              />
              {publications.map((publication) => (
                <article
                  key={publication.id}
                  className="rounded-lg border p-3 text-sm"
                >
                  <div className="flex items-center justify-between">
                    <strong>r{publication.revision}</strong>
                    <span className="font-mono text-xs text-muted-foreground">
                      {shortHash(publication.config_hash)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {formatDate(publication.created_at)} ·{" "}
                    {publication.created_by || "system"}
                  </p>
                  {publication.id !== detail.current_publication?.id &&
                  detail.permissions.can_publish ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="mt-3"
                      onClick={() =>
                        actions.rollback.mutate({
                          publicationId: publication.id,
                          expectedRevision: detail.definition.revision,
                        })
                      }
                    >
                      <RotateCcwIcon />
                      受控回退
                    </Button>
                  ) : null}
                </article>
              ))}
            </CardContent>
          </Card>
        </aside>
      </div>
    </ManagementPage>
  )
}

export function ModelConnectionPage() {
  const agentCode = useParams().agentCode ?? ""
  const connectionCode = useParams().connectionCode ?? ""
  const query = useModelConnection(connectionCode)
  if (query.isLoading)
    return (
      <ManagementPage>
        <ManagementLoading />
      </ManagementPage>
    )
  if (query.isError || !query.data)
    return (
      <ManagementPage>
        <Back to={`/agent-profiles/${encodeURIComponent(agentCode)}`} />
        <ManagementError
          error={query.error}
          retry={() => void query.refetch()}
        />
      </ManagementPage>
    )
  return (
    <ModelConnectionView
      key={`${query.data.revision}:${query.data.current_revision_id}`}
      agentCode={agentCode}
      connection={query.data}
    />
  )
}

function ModelConnectionView({
  agentCode,
  connection,
}: {
  agentCode: string
  connection: NonNullable<ReturnType<typeof useModelConnection>["data"]>
}) {
  const actions = useModelConnectionActions(connection.code)
  const [apiKey, setApiKey] = useState("")
  const current = connection.current_revision
  const error = actions.rotate.error || actions.test.error
  return (
    <ManagementPage>
      <Back to={`/agent-profiles/${encodeURIComponent(agentCode)}`} />
      <header>
        <p className="text-xs font-medium text-indigo-700">Model Connection</p>
        <h1 className="mt-1 text-2xl font-semibold">
          {connection.name ?? connection.code}
        </h1>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {connection.code} · connection r{connection.revision}
        </p>
      </header>
      <MutationNotice error={error} />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>当前版本</CardTitle>
            <p className="text-sm text-muted-foreground">
              浏览器只接收 Provider host 和非敏感配置，不返回完整地址或 Secret
              ref。
            </p>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
            <Summary label="状态" value={current?.status ?? "未配置"} />
            <Summary
              label="Provider host"
              value={current?.provider_host || "未配置"}
            />
            <Summary label="模型" value={current?.config.model || "未配置"} />
            <Summary
              label="配置 hash"
              value={shortHash(current?.config_hash)}
            />
            <Summary
              label="凭据"
              value={
                current?.credential?.configured
                  ? `已配置${current.credential.rotation_required ? "，需要轮换" : ""}`
                  : "未配置"
              }
            />
            <Summary
              label="Runtime probe"
              value={current?.last_test ? "已有结果" : "尚未测试"}
            />
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>凭据与真实测试</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {connection.permissions.can_manage_credential ? (
              <>
                <Label htmlFor="model-api-key">新 API Key</Label>
                <Input
                  id="model-api-key"
                  type="password"
                  autoComplete="new-password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  密钥仅在本次请求中提交，响应和前端状态不会保存服务端 Secret
                  标识。
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    disabled={!apiKey || !current || actions.rotate.isPending}
                    onClick={() =>
                      current &&
                      actions.rotate.mutate(
                        [connection.code, connection.revision, apiKey],
                        { onSuccess: () => setApiKey("") }
                      )
                    }
                  >
                    轮换凭据
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={
                      !current ||
                      !connection.permissions.can_test ||
                      actions.test.isPending
                    }
                    onClick={() =>
                      current &&
                      actions.test.mutate([
                        connection.code,
                        current.id,
                        connection.revision,
                      ])
                    }
                  >
                    运行短时测试
                  </Button>
                </div>
              </>
            ) : (
              <p className="rounded-lg border p-3 text-sm text-muted-foreground">
                你没有 Secret 管理权限，因此凭据写入与真实测试操作不可见。
              </p>
            )}
            {actions.test.data ? (
              <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">
                {JSON.stringify(actions.test.data, null, 2)}
              </pre>
            ) : null}
          </CardContent>
        </Card>
      </div>
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>版本历史</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {connection.revisions.map((revision) => (
            <div
              key={revision.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm"
            >
              <span>
                r{revision.revision} · {revision.status}
              </span>
              <span className="text-muted-foreground">
                {revision.provider_host || "host unavailable"} ·{" "}
                {formatDate(revision.created_at)}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
    </ManagementPage>
  )
}

function defaultConfig(detail: AgentDetail): AgentDraftConfig {
  const connection = detail.model_connections.find(
    (item) => item.current_revision_id
  )
  return {
    business_role: "",
    business_instructions: "",
    model_policy: {
      runtime: "claude_agent_sdk",
      model: detail.catalog.models[0] ?? "",
      model_connection_revision_id: connection?.current_revision_id ?? "",
    },
    execution: { max_turns: 12, timeout_seconds: 300 },
    skills: [],
    routing: { project_code: detail.definition.project_code },
    channels: { ingress: [], delivery: [] },
    mcp_tool_publication_ids: [],
  }
}
function toggleSet(current: Set<string>, id: string, checked: boolean) {
  const next = new Set(current)
  if (checked) next.add(id)
  else next.delete(id)
  return next
}
function runtimeFrom(snapshot?: Record<string, unknown>) {
  const value = snapshot?.runtime
  return typeof value === "string" ? value : "typescript-v1"
}
function lifecycleLabel(value: string) {
  return (
    (
      { enabled: "已启用", disabled: "已停用", archived: "已归档" } as Record<
        string,
        string
      >
    )[value] ?? value
  )
}
function lifecycleOptions(current: string) {
  if (current === "enabled")
    return [
      { value: "enabled", label: "已启用" },
      { value: "disabled", label: "停用" },
    ]
  if (current === "disabled")
    return [
      { value: "disabled", label: "已停用" },
      { value: "archived", label: "归档" },
    ]
  return [{ value: "archived", label: "已归档" }]
}
function shortHash(value?: string) {
  return value ? `${value.slice(0, 12)}…` : "—"
}
function formatDate(value?: string) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "—"
}
function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate font-medium" title={value}>
        {value}
      </p>
    </div>
  )
}
function Back({ to }: { to: string }) {
  return (
    <Link className={buttonVariants({ variant: "ghost", size: "sm" })} to={to}>
      <ArrowLeftIcon />
      返回
    </Link>
  )
}
function Field({
  label,
  name,
  required = false,
}: {
  label: string
  name: string
  required?: boolean
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={`create-${name}`}>{label}</Label>
      <Input id={`create-${name}`} name={name} required={required} />
    </div>
  )
}
function NativeSelect({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string
  value: string
  options: Array<{ value: string; label: string }>
  disabled: boolean
  onChange: (value: string) => void
}) {
  const id = `select-${label}`
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        className="h-9 w-full rounded-lg border bg-background px-3 text-sm"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">请选择</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}
function NumberField({
  label,
  value,
  min,
  max,
  disabled,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  disabled: boolean
  onChange: (value: number) => void
}) {
  const id = `number-${label}`
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </div>
  )
}
function TextField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string
  value: string
  disabled: boolean
  onChange: (value: string) => void
}) {
  const id = `agent-text-${label}`
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}
function ChoiceCard({
  title,
  help,
  options,
  selected,
  disabled,
  onToggle,
}: {
  title: string
  help: string
  options: Array<{ id: string; label: string; description: string }>
  selected: Set<string>
  disabled: boolean
  onToggle: (id: string, checked: boolean) => void
}) {
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <p className="text-sm text-muted-foreground">{help}</p>
      </CardHeader>
      <CardContent className="max-h-80 space-y-2 overflow-y-auto">
        {options.map((option) => (
          <label
            key={option.id}
            className="flex cursor-pointer items-start gap-3 rounded-lg border p-3"
          >
            <Checkbox
              checked={selected.has(option.id)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                onToggle(option.id, checked === true)
              }
            />
            <span className="min-w-0">
              <span className="block text-sm font-medium break-all">
                {option.label}
              </span>
              <span className="block text-xs text-muted-foreground">
                {option.description}
              </span>
            </span>
          </label>
        ))}
        {options.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无可选项。</p>
        ) : null}
      </CardContent>
    </Card>
  )
}
