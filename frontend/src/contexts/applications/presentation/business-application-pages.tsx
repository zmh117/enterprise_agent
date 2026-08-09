import { useState, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  AppWindowIcon,
  ArrowLeftIcon,
  EyeIcon,
  PlusIcon,
  RefreshCwIcon,
  SaveIcon,
  SendIcon,
  ShieldCheckIcon,
  XIcon,
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
  applicationKeys,
  useApplicationCatalog,
  useApplicationEffective,
  useBusinessApplication,
  useBusinessApplicationActions,
  useBusinessApplications,
} from "@/contexts/applications/application/business-application-queries"
import type {
  ApplicationCatalog,
  ApplicationDelivery,
  ApplicationDraftInput,
  ApplicationTrigger,
  BusinessApplicationDetail,
  Environment,
} from "@/contexts/applications/domain/business-application"
import { createBusinessApplication } from "@/contexts/applications/infrastructure/business-application-api"
import {
  ManagementError,
  ManagementLoading,
  ManagementPage,
  MutationNotice,
} from "@/shared/presentation/management-states"

export function BusinessApplicationListPage() {
  const query = useBusinessApplications()
  const [creating, setCreating] = useState(false)
  return (
    <ManagementPage>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-indigo-700">
            Application Control Plane
          </p>
          <h1 className="mt-1 text-2xl font-semibold">Business Applications</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            一个 Application 冻结一个 Agent Publication，并选择其 MCP/Resource
            子集和入口投递策略。
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
              新建应用
            </Button>
          ) : null}
        </div>
      </header>
      {creating ? (
        <CreateApplicationForm onClose={() => setCreating(false)} />
      ) : null}
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error} retry={() => void query.refetch()} />
      {query.data?.items.length === 0 ? (
        <Card className="shadow-none">
          <CardContent className="p-10 text-center">
            <AppWindowIcon className="mx-auto size-8 text-muted-foreground" />
            <p className="mt-3 font-medium">暂无可查看的业务应用</p>
            <p className="mt-1 text-sm text-muted-foreground">
              应用不会隐式创建；每个发布和环境激活都需要明确操作。
            </p>
          </CardContent>
        </Card>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {query.data?.items.map((application) => (
          <Card key={application.code} className="shadow-none">
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle>
                  <Link
                    className="hover:underline"
                    to={`/applications/${encodeURIComponent(application.code)}`}
                  >
                    {application.name}
                  </Link>
                </CardTitle>
                <Badge
                  variant={
                    application.status === "enabled" ? "secondary" : "outline"
                  }
                >
                  {lifecycleLabel(application.status)}
                </Badge>
              </div>
              <p className="font-mono text-xs text-muted-foreground">
                {application.code} · {application.project_code}
              </p>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
              <Summary label="Definition" value={`r${application.revision}`} />
              <Summary
                label="活动环境"
                value={
                  application.active_environments.length
                    ? application.active_environments.join("、")
                    : "未激活"
                }
              />
              <Summary
                label="Runtime"
                value={application.runtime_ready ? "已就绪" : "未就绪"}
              />
            </CardContent>
          </Card>
        ))}
      </div>
    </ManagementPage>
  )
}

function CreateApplicationForm({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const mutation = useMutation({
    mutationFn: createBusinessApplication,
    onSuccess: async (application) => {
      await client.invalidateQueries({ queryKey: applicationKeys.all })
      navigate(`/applications/${encodeURIComponent(application.code)}`)
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
      owner_user_id: String(form.get("owner_user_id") || ""),
    })
  }
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>新建 Business Application</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
          <Field label="代码" name="code" required />
          <Field label="名称" name="name" required />
          <Field label="项目代码" name="project_code" required />
          <Field label="Owner 用户 ID" name="owner_user_id" />
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="app-description">说明</Label>
            <Textarea id="app-description" name="description" />
          </div>
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

export function BusinessApplicationDetailPage() {
  const code = useParams().applicationCode ?? ""
  const detail = useBusinessApplication(code)
  const catalog = useApplicationCatalog(code)
  if (detail.isLoading || catalog.isLoading)
    return (
      <ManagementPage>
        <ManagementLoading />
      </ManagementPage>
    )
  if (detail.isError || !detail.data)
    return (
      <ManagementPage>
        <Back />
        <ManagementError
          error={detail.error}
          retry={() => void detail.refetch()}
        />
      </ManagementPage>
    )
  return (
    <ApplicationEditor
      key={`${detail.data.revision}:${detail.data.draft?.id ?? "none"}`}
      application={detail.data}
      catalog={catalog.data}
      catalogError={catalog.error}
      refreshCatalog={() => void catalog.refetch()}
    />
  )
}

function ApplicationEditor({
  application,
  catalog,
  catalogError,
  refreshCatalog,
}: {
  application: BusinessApplicationDetail
  catalog?: ApplicationCatalog
  catalogError: unknown
  refreshCatalog: () => void
}) {
  const actions = useBusinessApplicationActions(application.code)
  const initial = application.draft
    ? toDraft(application.draft)
    : defaultDraft()
  const [draft, setDraft] = useState(initial)
  const [selectedTools, setSelectedTools] = useState(
    new Set(initial.mcp_tool_publication_ids)
  )
  const [metadata, setMetadata] = useState({
    name: application.name,
    description: application.description,
    project_code: application.project_code,
    owner_user_id: application.owner_user_id,
    status: application.status,
  })
  const mutable =
    application.permissions.edit && application.status === "enabled"
  const toolOptions =
    catalog?.mcp_tools_by_agent_publication[draft.agent_publication_id] ?? []
  const error =
    actions.update.error ||
    actions.saveDraft.error ||
    actions.validate.error ||
    actions.publish.error ||
    actions.activate.error ||
    actions.deactivate.error
  return (
    <ManagementPage>
      <Back />
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold">{application.name}</h1>
            <Badge
              variant={
                application.status === "enabled" ? "secondary" : "outline"
              }
            >
              {lifecycleLabel(application.status)}
            </Badge>
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {application.code} · {application.project_code} · definition r
            {application.revision}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={
              !mutable || !application.draft || actions.validate.isPending
            }
            onClick={() =>
              application.draft &&
              actions.validate.mutate({
                revisionId: application.draft.id,
                expectedRevision: application.revision,
              })
            }
          >
            <ShieldCheckIcon />
            校验
          </Button>
          <Button
            type="button"
            disabled={
              !application.permissions.publish ||
              !application.draft ||
              actions.publish.isPending
            }
            onClick={() =>
              application.draft &&
              actions.publish.mutate({
                revisionId: application.draft.id,
                expectedRevision: application.revision,
              })
            }
          >
            <SendIcon />
            发布
          </Button>
        </div>
      </header>
      <MutationNotice error={error} />
      <ManagementError error={catalogError} retry={refreshCatalog} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(20rem,1fr)]">
        <div className="space-y-5">
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>应用定义与生命周期</CardTitle>
              <p className="text-sm text-muted-foreground">
                停用不会改写既有 Publication；归档前需停止活动环境。
              </p>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <TextField
                label="应用名称"
                value={metadata.name}
                disabled={!application.permissions.edit}
                onChange={(value) => setMetadata({ ...metadata, name: value })}
              />
              <TextField
                label="项目代码"
                value={metadata.project_code}
                disabled={!application.permissions.edit}
                onChange={(value) =>
                  setMetadata({ ...metadata, project_code: value })
                }
              />
              <TextField
                label="Owner 用户 ID"
                value={metadata.owner_user_id}
                disabled={!application.permissions.edit}
                onChange={(value) =>
                  setMetadata({ ...metadata, owner_user_id: value })
                }
              />
              <NativeSelect
                label="应用生命周期"
                value={metadata.status}
                disabled={!application.permissions.edit}
                options={lifecycleOptions(application.status)}
                onChange={(value) =>
                  setMetadata({
                    ...metadata,
                    status: value as typeof metadata.status,
                  })
                }
              />
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="application-description">说明</Label>
                <Textarea
                  id="application-description"
                  value={metadata.description}
                  disabled={!application.permissions.edit}
                  onChange={(event) =>
                    setMetadata({
                      ...metadata,
                      description: event.target.value,
                    })
                  }
                />
              </div>
              <Button
                type="button"
                variant="outline"
                className="w-fit"
                disabled={
                  !application.permissions.edit || actions.update.isPending
                }
                onClick={() =>
                  actions.update.mutate({
                    expectedRevision: application.revision,
                    ...metadata,
                  })
                }
              >
                <SaveIcon />
                保存应用定义
              </Button>
            </CardContent>
          </Card>
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>Agent Publication 与 MCP/Resource 子集</CardTitle>
              <p className="text-sm text-muted-foreground">
                切换 Agent Publication 会清空 Tool 选择，避免跨 Publication
                串用。
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <NativeSelect
                label="Agent Publication"
                value={draft.agent_publication_id}
                disabled={!mutable}
                options={(catalog?.agents ?? []).map((agent) => ({
                  value: agent.id,
                  label: `${agent.code} · r${agent.revision} · ${shortHash(agent.config_hash)}`,
                }))}
                onChange={(value) => {
                  setDraft({
                    ...draft,
                    agent_publication_id: value,
                    mcp_tool_publication_ids: [],
                  })
                  setSelectedTools(new Set())
                }}
              />
              <div
                className="max-h-80 space-y-2 overflow-y-auto"
                aria-label="MCP Tool 与 Resource 子集"
              >
                {toolOptions.map((tool) => (
                  <label
                    key={tool.id}
                    className="flex items-start gap-3 rounded-lg border p-3"
                  >
                    <Checkbox
                      checked={selectedTools.has(tool.id)}
                      disabled={!mutable}
                      onCheckedChange={(checked) => {
                        const next = toggleSet(
                          selectedTools,
                          tool.id,
                          checked === true
                        )
                        setSelectedTools(next)
                      }}
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium break-all">
                        {tool.server_code}.{tool.tool_name}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {tool.resource_kind
                          ? `${tool.resource_kind}/${tool.resource_code || "—"} · deployment ${shortHash(tool.resource_deployment_id)} · revision ${shortHash(tool.resource_revision_id)}`
                          : "不绑定 Resource"}
                      </span>
                    </span>
                  </label>
                ))}
                {draft.agent_publication_id && toolOptions.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    此 Agent Publication 没有可选 MCP Tool。
                  </p>
                ) : null}
              </div>
            </CardContent>
          </Card>
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>Session 与执行策略</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-3">
              <NumberField
                label="最近消息数"
                value={draft.session_policy.recent_message_limit}
                min={1}
                max={100}
                disabled={!mutable}
                onChange={(value) =>
                  setDraft({
                    ...draft,
                    session_policy: {
                      ...draft.session_policy,
                      recent_message_limit: value,
                    },
                  })
                }
              />
              <NumberField
                label="最大轮次"
                value={draft.execution_policy.max_turns}
                min={1}
                max={100}
                disabled={!mutable}
                onChange={(value) =>
                  setDraft({
                    ...draft,
                    execution_policy: {
                      ...draft.execution_policy,
                      max_turns: value,
                    },
                  })
                }
              />
              <NumberField
                label="最大 Tool 调用"
                value={draft.execution_policy.max_tool_calls}
                min={0}
                max={200}
                disabled={!mutable}
                onChange={(value) =>
                  setDraft({
                    ...draft,
                    execution_policy: {
                      ...draft.execution_policy,
                      max_tool_calls: value,
                    },
                  })
                }
              />
              <NumberField
                label="超时（秒）"
                value={draft.execution_policy.timeout_seconds}
                min={10}
                max={3600}
                disabled={!mutable}
                onChange={(value) =>
                  setDraft({
                    ...draft,
                    execution_policy: {
                      ...draft.execution_policy,
                      timeout_seconds: value,
                    },
                  })
                }
              />
              <NumberField
                label="保留天数"
                value={draft.session_policy.retention_days}
                min={1}
                max={3650}
                disabled={!mutable}
                onChange={(value) =>
                  setDraft({
                    ...draft,
                    session_policy: {
                      ...draft.session_policy,
                      retention_days: value,
                    },
                  })
                }
              />
            </CardContent>
          </Card>
          <TriggerEditor
            values={draft.triggers}
            catalog={catalog}
            disabled={!mutable}
            onChange={(triggers) => setDraft({ ...draft, triggers })}
          />
          <DeliveryEditor
            values={draft.deliveries}
            catalog={catalog}
            disabled={!mutable}
            onChange={(deliveries) => setDraft({ ...draft, deliveries })}
          />
          <div className="flex justify-end">
            <Button
              type="button"
              disabled={!mutable || actions.saveDraft.isPending}
              onClick={() =>
                actions.saveDraft.mutate({
                  expectedRevision: application.revision,
                  draft: {
                    ...draft,
                    mcp_tool_publication_ids: Array.from(selectedTools),
                  },
                })
              }
            >
              <SaveIcon />
              保存新草稿
            </Button>
          </div>
        </div>
        <aside className="space-y-5">
          <DeploymentCard
            application={application}
            environment="test"
            actions={actions}
          />
          <DeploymentCard
            application={application}
            environment="production"
            actions={actions}
          />
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>Publication 历史</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {application.publications.map((publication) => (
                <article
                  key={publication.id}
                  className="rounded-lg border p-3 text-sm"
                >
                  <div className="flex justify-between gap-2">
                    <strong>r{publication.revision}</strong>
                    <Badge
                      variant={
                        publication.runtime_ready ? "secondary" : "outline"
                      }
                    >
                      {publication.runtime_ready
                        ? "Runtime ready"
                        : "Not ready"}
                    </Badge>
                  </div>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {shortHash(publication.config_hash)}
                  </p>
                  {application.permissions.activate ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <ActivateButton
                        application={application}
                        environment="test"
                        publicationId={publication.id}
                        actions={actions}
                      />
                      <ActivateButton
                        application={application}
                        environment="production"
                        publicationId={publication.id}
                        actions={actions}
                      />
                    </div>
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

function TriggerEditor({
  values,
  catalog,
  disabled,
  onChange,
}: {
  values: ApplicationTrigger[]
  catalog?: ApplicationCatalog
  disabled: boolean
  onChange: (values: ApplicationTrigger[]) => void
}) {
  const connectors =
    catalog?.connectors.filter((item) => item.allow_ingress) ?? []
  const update = (index: number, value: ApplicationTrigger) =>
    onChange(values.map((item, current) => (current === index ? value : item)))
  return (
    <Card className="shadow-none">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Channel / Trigger</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              路由键必须唯一；主体策略在发布时再次校验。
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled || values.length >= 20}
            onClick={() => onChange([...values, defaultTrigger()])}
          >
            <PlusIcon />
            添加入口
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {values.map((trigger, index) => (
          <div
            key={index}
            className="grid gap-3 rounded-lg border p-3 sm:grid-cols-2"
          >
            <NativeSelect
              label={`入口类型 ${index + 1}`}
              value={trigger.trigger_type}
              disabled={disabled}
              options={[
                { value: "dingtalk_private", label: "钉钉单聊" },
                { value: "dingtalk_group", label: "钉钉群聊" },
                { value: "webhook", label: "Webhook" },
              ]}
              onChange={(value) =>
                update(index, {
                  ...trigger,
                  trigger_type: value as ApplicationTrigger["trigger_type"],
                })
              }
            />
            <NativeSelect
              label={`入口连接器 ${index + 1}`}
              value={trigger.connector_id}
              disabled={disabled}
              options={connectors.map((item) => ({
                value: item.id,
                label: `${item.name} · ${item.connector_type}`,
              }))}
              onChange={(value) =>
                update(index, { ...trigger, connector_id: value })
              }
            />
            <TextField
              label={`路由键 ${index + 1}`}
              value={trigger.routing_key}
              disabled={disabled}
              onChange={(value) =>
                update(index, { ...trigger, routing_key: value })
              }
            />
            <NativeSelect
              label={`主体策略 ${index + 1}`}
              value={trigger.actor_policy}
              disabled={disabled}
              options={[
                { value: "CURRENT_SENDER", label: "当前发送者" },
                { value: "SERVICE_ACCOUNT", label: "服务账号" },
              ]}
              onChange={(value) =>
                update(index, {
                  ...trigger,
                  actor_policy: value as ApplicationTrigger["actor_policy"],
                })
              }
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={disabled}
              onClick={() =>
                onChange(values.filter((_, current) => current !== index))
              }
            >
              <XIcon />
              移除入口
            </Button>
          </div>
        ))}
        {values.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            尚未配置入口，应用无法接收新消息。
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function DeliveryEditor({
  values,
  catalog,
  disabled,
  onChange,
}: {
  values: ApplicationDelivery[]
  catalog?: ApplicationCatalog
  disabled: boolean
  onChange: (values: ApplicationDelivery[]) => void
}) {
  const connectors =
    catalog?.connectors.filter(
      (item) => item.allow_delivery || item.allow_ingress
    ) ?? []
  const update = (index: number, value: ApplicationDelivery) =>
    onChange(values.map((item, current) => (current === index ? value : item)))
  return (
    <Card className="shadow-none">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Delivery</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              结果只投递到发布时冻结并允许的连接器。
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled || values.length >= 20}
            onClick={() => onChange([...values, defaultDelivery()])}
          >
            <PlusIcon />
            添加投递
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {values.map((delivery, index) => (
          <div
            key={index}
            className="grid gap-3 rounded-lg border p-3 sm:grid-cols-2"
          >
            <NativeSelect
              label={`投递类型 ${index + 1}`}
              value={delivery.delivery_type}
              disabled={disabled}
              options={[
                { value: "reply_original", label: "回复原会话" },
                { value: "dingtalk_private", label: "钉钉单聊" },
                { value: "dingtalk_group", label: "钉钉群聊" },
                { value: "webhook_callback", label: "Webhook Callback" },
              ]}
              onChange={(value) =>
                update(index, {
                  ...delivery,
                  delivery_type: value as ApplicationDelivery["delivery_type"],
                })
              }
            />
            <NativeSelect
              label={`投递连接器 ${index + 1}`}
              value={delivery.connector_id}
              disabled={disabled}
              options={connectors.map((item) => ({
                value: item.id,
                label: `${item.name} · ${item.connector_type}`,
              }))}
              onChange={(value) =>
                update(index, { ...delivery, connector_id: value })
              }
            />
            <TextField
              label={`目标引用 ${index + 1}`}
              value={delivery.config.target_reference}
              disabled={disabled}
              onChange={(value) =>
                update(index, {
                  ...delivery,
                  config: { ...delivery.config, target_reference: value },
                })
              }
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={disabled}
              onClick={() =>
                onChange(values.filter((_, current) => current !== index))
              }
            >
              <XIcon />
              移除投递
            </Button>
          </div>
        ))}
        {values.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            尚未配置投递，Job 结果不会发送到外部渠道。
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function DeploymentCard({
  application,
  environment,
  actions,
}: {
  application: BusinessApplicationDetail
  environment: Environment
  actions: ReturnType<typeof useBusinessApplicationActions>
}) {
  const deployment = application.deployments.find(
    (item) => item.environment === environment
  )
  const effective = useApplicationEffective(
    application.code,
    environment,
    Boolean(deployment?.active)
  )
  return (
    <Card className="shadow-none">
      <CardHeader>
        <div className="flex justify-between gap-2">
          <CardTitle>{environment} 环境</CardTitle>
          <Badge variant={deployment?.active ? "secondary" : "outline"}>
            {deployment?.active ? "已激活" : "未激活"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <Summary
          label="Deployment revision"
          value={`r${deployment?.revision ?? 0}`}
        />
        <Summary
          label="Publication"
          value={shortHash(deployment?.publication_id)}
        />
        {deployment?.active && application.permissions.activate ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={actions.deactivate.isPending}
            onClick={() =>
              actions.deactivate.mutate({
                environment,
                expectedRevision: deployment.revision,
              })
            }
          >
            停用
          </Button>
        ) : null}
        {deployment?.active ? (
          <details>
            <summary className="cursor-pointer text-sm font-medium">
              <EyeIcon className="mr-1 inline size-4" />
              Effective preview
            </summary>
            {effective.isLoading ? (
              <p className="mt-2 text-muted-foreground">正在加载…</p>
            ) : null}
            <ManagementError
              error={effective.error}
              retry={() => void effective.refetch()}
            />
            {effective.data ? (
              <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs">
                {JSON.stringify(safeEffective(effective.data), null, 2)}
              </pre>
            ) : null}
          </details>
        ) : null}
      </CardContent>
    </Card>
  )
}

function ActivateButton({
  application,
  environment,
  publicationId,
  actions,
}: {
  application: BusinessApplicationDetail
  environment: Environment
  publicationId: string
  actions: ReturnType<typeof useBusinessApplicationActions>
}) {
  const deployment = application.deployments.find(
    (item) => item.environment === environment
  )
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      disabled={
        actions.activate.isPending ||
        (deployment?.active && deployment.publication_id === publicationId)
      }
      onClick={() =>
        actions.activate.mutate({
          environment,
          publicationId,
          expectedRevision: deployment?.revision ?? 0,
        })
      }
    >
      激活 {environment}
    </Button>
  )
}
function toDraft(
  value: BusinessApplicationDetail["draft"]
): ApplicationDraftInput {
  if (!value) return defaultDraft()
  return {
    agent_publication_id: value.agent_publication_id,
    mcp_tool_publication_ids: value.mcp_tool_publication_ids ?? [],
    session_policy: value.session_policy,
    execution_policy: value.execution_policy,
    triggers: value.triggers ?? [],
    deliveries: value.deliveries ?? [],
  }
}
function defaultDraft(): ApplicationDraftInput {
  return {
    agent_publication_id: "",
    mcp_tool_publication_ids: [],
    session_policy: {
      conversation_mode: "channel",
      recent_message_limit: 20,
      retention_days: 30,
      continuous_conversation_enabled: false,
      attachments_enabled: false,
    },
    execution_policy: {
      max_turns: 12,
      timeout_seconds: 300,
      max_tool_calls: 30,
    },
    triggers: [],
    deliveries: [],
  }
}
function defaultTrigger(): ApplicationTrigger {
  return {
    trigger_type: "dingtalk_private",
    connector_id: "",
    routing_key: "",
    actor_policy: "CURRENT_SENDER",
    service_account_user_id: "",
    enabled: true,
    config: {
      conversation_type: "",
      require_mention: false,
      webhook_definition_id: "",
    },
  }
}
function defaultDelivery(): ApplicationDelivery {
  return {
    delivery_type: "reply_original",
    connector_id: "",
    enabled: true,
    config: { target_reference: "", reply_mode: "" },
  }
}
function safeEffective(value: Record<string, unknown>) {
  const {
    application,
    deployment,
    publication,
    runtime_ready,
    readiness_errors,
  } = value
  return {
    application,
    deployment,
    publication,
    runtime_ready,
    readiness_errors,
  }
}
function toggleSet(current: Set<string>, id: string, checked: boolean) {
  const next = new Set(current)
  if (checked) next.add(id)
  else next.delete(id)
  return next
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
function shortHash(value?: string | null) {
  return value ? `${value.slice(0, 12)}…` : "—"
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
function Back() {
  return (
    <Link
      className={buttonVariants({ variant: "ghost", size: "sm" })}
      to="/applications"
    >
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
      <Label htmlFor={`create-app-${name}`}>{label}</Label>
      <Input id={`create-app-${name}`} name={name} required={required} />
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
  const id = `app-select-${label}`
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
  const id = `app-number-${label}`
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
  const id = `app-text-${label}`
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
