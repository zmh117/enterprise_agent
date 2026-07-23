import { useState, type FormEvent } from "react"
import {
  AlertCircleIcon,
  ArrowLeftIcon,
  CheckCircle2Icon,
  Clock3Icon,
  GitBranchIcon,
  LoaderCircleIcon,
  PackageCheckIcon,
  PowerIcon,
  SaveIcon,
  ShieldAlertIcon,
  WorkflowIcon,
} from "lucide-react"
import { Link, useParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  useActivatePublication,
  useApplication,
  useApplicationCatalog,
  useDeactivateEnvironment,
  usePublishDraft,
  useSaveDraft,
  useUpdateApplication,
  useValidateDraft,
} from "@/contexts/applications/application/business-application-queries"
import type {
  BusinessApplication,
  SaveDraftInput,
} from "@/contexts/applications/domain/business-application"
import { ApplicationState } from "@/contexts/applications/presentation/application-state"
import {
  MutationError,
  StatusBadge,
} from "@/contexts/applications/presentation/applications-page"

export function ApplicationDetailPage() {
  const code = useParams().code ?? ""
  const query = useApplication(code)

  if (query.isLoading) {
    return (
      <div className="mx-auto w-full max-w-[1500px] space-y-5 px-4 py-6 sm:px-6 lg:px-8">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }
  if (query.isError || !query.data) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6">
        <ApplicationState
          error={query.error}
          retry={() => void query.refetch()}
        />
      </div>
    )
  }
  return <ApplicationWorkspace key={query.data.revision} application={query.data} />
}

function ApplicationWorkspace({
  application,
}: {
  application: BusinessApplication
}) {
  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header>
        <Link
          to="/applications"
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeftIcon aria-hidden="true" />
          返回应用列表
        </Link>
        <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">
                {application.name}
              </h1>
              <StatusBadge status={application.status} />
              <Badge variant="outline">r{application.revision}</Badge>
            </div>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {application.code} · {application.project_code}
            </p>
          </div>
          <Badge
            variant="outline"
            className="border-amber-300 bg-amber-50 text-amber-900"
          >
            runtime_wired=false · 尚未接管入口
          </Badge>
        </div>
      </header>

      <Tabs defaultValue="overview">
        <TabsList className="h-auto w-full justify-start overflow-x-auto">
          <TabsTrigger value="overview">概览</TabsTrigger>
          <TabsTrigger value="composition">组成配置</TabsTrigger>
          <TabsTrigger value="validation">校验结果</TabsTrigger>
          <TabsTrigger value="publications">发布与环境</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab application={application} />
        </TabsContent>
        <TabsContent value="composition">
          <CompositionTab application={application} />
        </TabsContent>
        <TabsContent value="validation">
          <ValidationTab application={application} />
        </TabsContent>
        <TabsContent value="publications">
          <PublicationTab application={application} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function OverviewTab({ application }: { application: BusinessApplication }) {
  const update = useUpdateApplication(application.code)
  const [form, setForm] = useState({
    name: application.name,
    description: application.description,
    project_code: application.project_code,
    owner_user_id: application.owner_user_id,
    status: application.status,
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    update.mutate({
      expected_revision: application.revision,
      ...form,
    })
  }

  const draft = application.draft
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>应用元数据</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="应用名称" htmlFor="detail-name">
                <Input
                  id="detail-name"
                  required
                  maxLength={200}
                  value={form.name}
                  onChange={(event) =>
                    setForm({ ...form, name: event.target.value })
                  }
                />
              </Field>
              <Field label="项目编码" htmlFor="detail-project">
                <Input
                  id="detail-project"
                  required
                  maxLength={120}
                  value={form.project_code}
                  onChange={(event) =>
                    setForm({ ...form, project_code: event.target.value })
                  }
                />
              </Field>
              <Field label="负责人用户 ID" htmlFor="detail-owner">
                <Input
                  id="detail-owner"
                  maxLength={200}
                  value={form.owner_user_id}
                  onChange={(event) =>
                    setForm({ ...form, owner_user_id: event.target.value })
                  }
                />
              </Field>
              <Field label="生命周期" htmlFor="detail-status">
                <select
                  id="detail-status"
                  className={selectClass}
                  value={form.status}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      status: event.target.value as typeof form.status,
                    })
                  }
                >
                  <option value="enabled">已启用</option>
                  <option value="disabled">已停用</option>
                  <option value="archived">已归档</option>
                </select>
              </Field>
            </div>
            <Field label="用途说明" htmlFor="detail-description">
              <textarea
                id="detail-description"
                className={textareaClass}
                maxLength={4000}
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
            </Field>
            <MutationError error={update.error} />
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : (
                <SaveIcon aria-hidden="true" />
              )}
              保存元数据
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <SummaryCard
          title="当前草稿"
          icon={GitBranchIcon}
          rows={[
            ["修订", draft ? `r${draft.revision}` : "无"],
            ["状态", draft?.status ?? "无"],
            ["Agent", draft?.agent_publication_id || "未选择"],
            ["Workflow", draft?.workflow_publication_id || "未选择"],
          ]}
        />
        <SummaryCard
          title="控制面摘要"
          icon={PackageCheckIcon}
          rows={[
            ["发布数量", String(application.publications.length)],
            [
              "活动环境",
              String(application.deployments.filter((item) => item.active).length),
            ],
            ["Capability 目录", "未接入"],
            ["数据面", "未接线"],
          ]}
        />
      </div>
    </div>
  )
}

function CompositionTab({ application }: { application: BusinessApplication }) {
  const catalog = useApplicationCatalog(application.code)
  const save = useSaveDraft(application.code)
  const draft = application.draft
  const [form, setForm] = useState<SaveDraftInput>(() => draftToForm(application))

  function submit(event: FormEvent) {
    event.preventDefault()
    save.mutate(form)
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>已发布组件</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <Field label="Agent Publication" htmlFor="draft-agent">
            <select
              id="draft-agent"
              className={selectClass}
              required
              value={form.agent_publication_id}
              onChange={(event) =>
                setForm({ ...form, agent_publication_id: event.target.value })
              }
            >
              <option value="">请选择已发布 Agent</option>
              {catalog.data?.agents.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.code} · r{item.revision}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Workflow Publication（可选）" htmlFor="draft-workflow">
            <select
              id="draft-workflow"
              className={selectClass}
              value={form.workflow_publication_id}
              onChange={(event) =>
                setForm({
                  ...form,
                  workflow_publication_id: event.target.value,
                })
              }
            >
              <option value="">不引用 Workflow</option>
              {catalog.data?.workflows.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.code} · v{item.revision}
                </option>
              ))}
            </select>
          </Field>
          {catalog.isError ? (
            <div className="md:col-span-2">
              <MutationError error={catalog.error} />
            </div>
          ) : null}
          <div className="rounded-md border bg-muted/35 p-3 text-sm text-muted-foreground md:col-span-2">
            <WorkflowIcon className="mr-2 inline size-4" aria-hidden="true" />
            流程设计画布不在本阶段实现；这里只冻结已发布 Workflow 引用。
          </div>
        </CardContent>
      </Card>

      <PolicyEditor form={form} setForm={setForm} />
      <BindingsEditor form={form} setForm={setForm} catalog={catalog.data} />

      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>API Capability</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border border-dashed p-4 text-sm leading-6 text-muted-foreground">
            Capability Catalog 尚未接入，当前列表必须为空。这里不提供任意
            Capability 编码、HTTP URL、SQL、Redis、Loki、Shell 或工具名输入。
          </div>
        </CardContent>
      </Card>

      <MutationError error={save.error} />
      <div className="sticky bottom-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-background/95 p-3 shadow-lg backdrop-blur">
        <p className="text-xs text-muted-foreground">
          保存将基于 expected revision r{application.revision} 创建新的追加式草稿。
        </p>
        <Button type="submit" disabled={save.isPending || catalog.isLoading}>
          {save.isPending ? (
            <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
          ) : (
            <SaveIcon aria-hidden="true" />
          )}
          保存新草稿
        </Button>
      </div>
      {draft ? (
        <p className="sr-only">当前草稿修订为 {draft.revision}</p>
      ) : null}
    </form>
  )
}

function PolicyEditor({
  form,
  setForm,
}: {
  form: SaveDraftInput
  setForm: (value: SaveDraftInput) => void
}) {
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>会话与执行策略</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Field label="会话范围" htmlFor="policy-conversation">
          <select
            id="policy-conversation"
            className={selectClass}
            value={form.session_policy.conversation_mode}
            onChange={(event) =>
              setForm({
                ...form,
                session_policy: {
                  ...form.session_policy,
                  conversation_mode: event.target
                    .value as SaveDraftInput["session_policy"]["conversation_mode"],
                },
              })
            }
          >
            <option value="channel">按渠道会话</option>
            <option value="actor">按当前主体</option>
            <option value="application">按应用</option>
          </select>
        </Field>
        <NumberField
          id="policy-recent"
          label="最近消息数"
          value={form.session_policy.recent_message_limit}
          min={1}
          max={100}
          onChange={(value) =>
            setForm({
              ...form,
              session_policy: {
                ...form.session_policy,
                recent_message_limit: value,
              },
            })
          }
        />
        <NumberField
          id="policy-retention"
          label="会话保留天数"
          value={form.session_policy.retention_days}
          min={1}
          max={3650}
          onChange={(value) =>
            setForm({
              ...form,
              session_policy: { ...form.session_policy, retention_days: value },
            })
          }
        />
        <NumberField
          id="policy-turns"
          label="最大轮次"
          value={form.execution_policy.max_turns}
          min={1}
          max={100}
          onChange={(value) =>
            setForm({
              ...form,
              execution_policy: { ...form.execution_policy, max_turns: value },
            })
          }
        />
        <NumberField
          id="policy-timeout"
          label="超时秒数"
          value={form.execution_policy.timeout_seconds}
          min={10}
          max={3600}
          onChange={(value) =>
            setForm({
              ...form,
              execution_policy: {
                ...form.execution_policy,
                timeout_seconds: value,
              },
            })
          }
        />
        <NumberField
          id="policy-tools"
          label="最大工具调用"
          value={form.execution_policy.max_tool_calls}
          min={0}
          max={200}
          onChange={(value) =>
            setForm({
              ...form,
              execution_policy: {
                ...form.execution_policy,
                max_tool_calls: value,
              },
            })
          }
        />
      </CardContent>
    </Card>
  )
}

type Catalog = ReturnType<typeof useApplicationCatalog>["data"]

function BindingsEditor({
  form,
  setForm,
  catalog,
}: {
  form: SaveDraftInput
  setForm: (value: SaveDraftInput) => void
  catalog: Catalog
}) {
  const ingress = uniqueConnectors(
    catalog?.connectors.filter((item) => item.direction === "ingress") ?? [],
  )
  const delivery = uniqueConnectors(
    catalog?.connectors.filter((item) => item.direction === "delivery") ?? [],
  )
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card className="shadow-none">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Trigger Bindings</CardTitle>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() =>
              setForm({
                ...form,
                triggers: [
                  ...form.triggers,
                  {
                    trigger_type: "dingtalk_private",
                    connector_id: ingress[0]?.id ?? "",
                    routing_key: "default",
                    actor_policy: "CURRENT_SENDER",
                    service_account_user_id: "",
                    enabled: true,
                    config: {
                      conversation_type: "private",
                      require_mention: false,
                      webhook_definition_id: "",
                    },
                  },
                ],
              })
            }
          >
            添加 Trigger
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {form.triggers.length === 0 ? (
            <EmptyBinding text="尚未配置 Trigger；应用可以发布，但不会产生入口路由。" />
          ) : null}
          {form.triggers.map((trigger, index) => (
            <div key={index} className="space-y-3 rounded-lg border p-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field
                  label={`Trigger ${index + 1} 类型`}
                  htmlFor={`trigger-type-${index}`}
                >
                  <select
                    id={`trigger-type-${index}`}
                    className={selectClass}
                    value={trigger.trigger_type}
                    onChange={(event) => {
                      const type = event.target
                        .value as SaveDraftInput["triggers"][number]["trigger_type"]
                      changeTrigger(form, setForm, index, {
                        trigger_type: type,
                        actor_policy:
                          type === "webhook"
                            ? "SERVICE_ACCOUNT"
                            : "CURRENT_SENDER",
                      })
                    }}
                  >
                    <option value="dingtalk_private">钉钉私聊</option>
                    <option value="dingtalk_group">钉钉群聊</option>
                    <option value="webhook">Webhook</option>
                  </select>
                </Field>
                <Field label="入口 Connector" htmlFor={`trigger-connector-${index}`}>
                  <select
                    id={`trigger-connector-${index}`}
                    className={selectClass}
                    value={trigger.connector_id}
                    onChange={(event) =>
                      changeTrigger(form, setForm, index, {
                        connector_id: event.target.value,
                      })
                    }
                  >
                    <option value="">请选择入口 Connector</option>
                    {ingress.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.code} · {item.component_type}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Routing Key" htmlFor={`trigger-route-${index}`}>
                  <Input
                    id={`trigger-route-${index}`}
                    required
                    maxLength={240}
                    value={trigger.routing_key}
                    onChange={(event) =>
                      changeTrigger(form, setForm, index, {
                        routing_key: event.target.value,
                      })
                    }
                  />
                </Field>
                <Field label="主体策略" htmlFor={`trigger-actor-${index}`}>
                  <Input
                    id={`trigger-actor-${index}`}
                    readOnly
                    value={trigger.actor_policy}
                  />
                </Field>
                {trigger.actor_policy === "SERVICE_ACCOUNT" ? (
                  <Field
                    label="服务账号用户 ID"
                    htmlFor={`trigger-service-${index}`}
                  >
                    <Input
                      id={`trigger-service-${index}`}
                      required
                      maxLength={200}
                      value={trigger.service_account_user_id}
                      onChange={(event) =>
                        changeTrigger(form, setForm, index, {
                          service_account_user_id: event.target.value,
                        })
                      }
                    />
                  </Field>
                ) : null}
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() =>
                  setForm({
                    ...form,
                    triggers: form.triggers.filter((_, item) => item !== index),
                  })
                }
              >
                删除 Trigger
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="shadow-none">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Delivery Bindings</CardTitle>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() =>
              setForm({
                ...form,
                deliveries: [
                  ...form.deliveries,
                  {
                    delivery_type: "dingtalk_private",
                    connector_id: delivery[0]?.id ?? "",
                    enabled: true,
                    config: { target_reference: "", reply_mode: "configured" },
                  },
                ],
              })
            }
          >
            添加 Delivery
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {form.deliveries.length === 0 ? (
            <EmptyBinding text="尚未配置 Delivery；发布不会改变现有结果投递链。" />
          ) : null}
          {form.deliveries.map((binding, index) => (
            <div key={index} className="space-y-3 rounded-lg border p-3">
              <Field
                label={`Delivery ${index + 1} 类型`}
                htmlFor={`delivery-type-${index}`}
              >
                <select
                  id={`delivery-type-${index}`}
                  className={selectClass}
                  value={binding.delivery_type}
                  onChange={(event) =>
                    changeDelivery(form, setForm, index, {
                      delivery_type: event.target
                        .value as SaveDraftInput["deliveries"][number]["delivery_type"],
                    })
                  }
                >
                  <option value="reply_original">回复原会话</option>
                  <option value="dingtalk_private">钉钉私聊</option>
                  <option value="dingtalk_group">钉钉群聊</option>
                  <option value="webhook_callback">Webhook 回调</option>
                </select>
              </Field>
              <Field label="Delivery Connector" htmlFor={`delivery-connector-${index}`}>
                <select
                  id={`delivery-connector-${index}`}
                  className={selectClass}
                  value={binding.connector_id}
                  onChange={(event) =>
                    changeDelivery(form, setForm, index, {
                      connector_id: event.target.value,
                    })
                  }
                >
                  <option value="">请选择投递 Connector</option>
                  {(binding.delivery_type === "reply_original"
                    ? ingress
                    : delivery
                  ).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.code} · {item.component_type}
                    </option>
                  ))}
                </select>
              </Field>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() =>
                  setForm({
                    ...form,
                    deliveries: form.deliveries.filter(
                      (_, item) => item !== index,
                    ),
                  })
                }
              >
                删除 Delivery
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

function ValidationTab({ application }: { application: BusinessApplication }) {
  const validate = useValidateDraft(application.code)
  const publish = usePublishDraft(application.code)
  const revision = application.draft
  const validation = revision?.validation
  const canPublish =
    application.status === "enabled" &&
    Boolean(revision) &&
    validation?.valid === true

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>跨组件校验</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!revision ? (
            <EmptyBinding text="当前没有草稿修订。" />
          ) : validation?.valid ? (
            <div
              className="flex items-start gap-3 rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-emerald-950"
              role="status"
            >
              <CheckCircle2Icon className="mt-0.5 size-5" aria-hidden="true" />
              <div>
                <p className="font-medium">草稿校验通过</p>
                <p className="mt-1 text-sm">
                  r{revision.revision} 可以创建不可变 publication。
                </p>
              </div>
            </div>
          ) : (
            <div
              className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950"
              role="alert"
            >
              <div className="flex items-center gap-2 font-medium">
                <ShieldAlertIcon className="size-5" aria-hidden="true" />
                尚未通过校验
              </div>
              {validation?.errors.length ? (
                <ul className="mt-3 space-y-2 text-sm">
                  {validation.errors.map((item, index) => (
                    <li key={`${item.field}-${index}`} className="rounded border bg-white/60 p-2">
                      <span className="font-mono text-xs">{item.field}</span>
                      <span className="ml-2">{item.message}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm">运行校验以检查全部组件和策略。</p>
              )}
            </div>
          )}
          <MutationError error={validate.error ?? publish.error} />
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!revision || validate.isPending}
              onClick={() => revision && validate.mutate(revision.id)}
            >
              {validate.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : (
                <AlertCircleIcon aria-hidden="true" />
              )}
              运行完整校验
            </Button>
            <Button
              type="button"
              disabled={!canPublish || publish.isPending}
              title={
                canPublish ? "创建不可变发布" : "必须先通过校验且应用处于启用状态"
              }
              onClick={() => revision && publish.mutate(revision.id)}
            >
              {publish.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : (
                <PackageCheckIcon aria-hidden="true" />
              )}
              发布当前修订
            </Button>
          </div>
        </CardContent>
      </Card>
      <SummaryCard
        title="校验范围"
        icon={ShieldAlertIcon}
        rows={[
          ["应用状态", application.status],
          ["Agent Publication", revision?.agent_publication_id || "未选择"],
          ["Workflow Publication", revision?.workflow_publication_id || "可选"],
          ["Trigger", String(revision?.triggers.length ?? 0)],
          ["Delivery", String(revision?.deliveries.length ?? 0)],
          ["Capability", String(revision?.capabilities.length ?? 0)],
        ]}
      />
    </div>
  )
}

function PublicationTab({ application }: { application: BusinessApplication }) {
  const activate = useActivatePublication(application.code)
  const deactivate = useDeactivateEnvironment(application.code)
  const [environment, setEnvironment] = useState("test")
  const deployment = application.deployments.find(
    (item) => item.environment === environment,
  )
  const error = activate.error ?? deactivate.error
  return (
    <div className="space-y-5">
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>环境 Deployment</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field label="目标环境" htmlFor="deployment-environment">
            <select
              id="deployment-environment"
              className={`${selectClass} max-w-xs`}
              value={environment}
              onChange={(event) => setEnvironment(event.target.value)}
            >
              <option value="test">test</option>
              <option value="staging">staging</option>
              <option value="production">production</option>
              <option value="local">local</option>
            </select>
          </Field>
          <div className="rounded-lg border bg-muted/30 p-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={deployment?.active ? "default" : "secondary"}>
                {deployment?.active ? "已激活" : "未激活"}
              </Badge>
              <span>{environment}</span>
              <span className="text-muted-foreground">
                deployment revision r{deployment?.revision ?? 0}
              </span>
            </div>
            <p className="mt-2 font-mono text-xs text-muted-foreground">
              publication: {deployment?.publication_id || "none"}
            </p>
          </div>
          {deployment?.active ? (
            <Button
              type="button"
              variant="destructive"
              disabled={deactivate.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `确认停用 ${environment} 环境？这只移除控制面活动路由投影。`,
                  )
                ) {
                  deactivate.mutate({
                    environment,
                    expectedRevision: deployment.revision,
                  })
                }
              }}
            >
              <PowerIcon aria-hidden="true" />
              停用环境
            </Button>
          ) : null}
          <MutationError error={error} />
          <p className="text-xs leading-5 text-muted-foreground">
            激活和停用不会接管现有钉钉/Webhook。后续数据面接线需要独立变更和灰度回退验证。
          </p>
        </CardContent>
      </Card>

      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>Publication 历史</CardTitle>
        </CardHeader>
        <CardContent>
          {application.publications.length === 0 ? (
            <EmptyBinding text="尚无 publication。先在校验页发布一个合法草稿。" />
          ) : (
            <div className="space-y-3">
              {application.publications.map((publication) => (
                <article
                  key={publication.id}
                  className="flex flex-col gap-3 rounded-lg border p-4 lg:flex-row lg:items-center"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">r{publication.revision}</Badge>
                      <span className="font-medium">{publication.id}</span>
                    </div>
                    <div className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                      <span>hash: {publication.config_hash.slice(0, 16)}…</span>
                      <span>发布人: {publication.published_by}</span>
                      <span>
                        发布时间: {formatDate(publication.published_at)}
                      </span>
                      <span>schema: v{publication.schema_version}</span>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={
                      application.status !== "enabled" || activate.isPending
                    }
                    title={
                      application.status === "enabled"
                        ? `激活到 ${environment}`
                        : "应用停用或归档时不能激活"
                    }
                    onClick={() => {
                      const action =
                        deployment?.active &&
                        deployment.publication_id !== publication.id
                          ? "回退"
                          : "激活"
                      if (
                        window.confirm(
                          `确认将 publication r${publication.revision} ${action}到 ${environment} 环境？这只更新控制面，不会接管钉钉或 Webhook。`,
                        )
                      ) {
                        activate.mutate({
                          environment,
                          publicationId: publication.id,
                          expectedRevision: deployment?.revision ?? 0,
                        })
                      }
                    }}
                  >
                    <Clock3Icon aria-hidden="true" />
                    {deployment?.publication_id === publication.id &&
                    deployment.active
                      ? "当前版本"
                      : "激活此版本"}
                  </Button>
                </article>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function SummaryCard({
  title,
  icon: Icon,
  rows,
}: {
  title: string
  icon: typeof GitBranchIcon
  rows: Array<[string, string]>
}) {
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="size-4" aria-hidden="true" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="space-y-3 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="min-w-0 truncate text-right font-medium" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  )
}

function NumberField({
  id,
  label,
  value,
  min,
  max,
  onChange,
}: {
  id: string
  label: string
  value: number
  min: number
  max: number
  onChange: (value: number) => void
}) {
  return (
    <Field label={label} htmlFor={id}>
      <Input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </Field>
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

function EmptyBinding({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
      {text}
    </div>
  )
}

function draftToForm(application: BusinessApplication): SaveDraftInput {
  const draft = application.draft
  return {
    expected_revision: application.revision,
    agent_publication_id: draft?.agent_publication_id ?? "",
    workflow_publication_id: draft?.workflow_publication_id ?? "",
    session_policy: {
      conversation_mode:
        (draft?.session_policy.conversation_mode as
          | "channel"
          | "actor"
          | "application") ?? "channel",
      recent_message_limit: Number(
        draft?.session_policy.recent_message_limit ?? 20,
      ),
      retention_days: Number(draft?.session_policy.retention_days ?? 30),
    },
    execution_policy: {
      max_turns: Number(draft?.execution_policy.max_turns ?? 12),
      timeout_seconds: Number(draft?.execution_policy.timeout_seconds ?? 300),
      max_tool_calls: Number(draft?.execution_policy.max_tool_calls ?? 30),
    },
    triggers:
      draft?.triggers.map((item) => ({
        trigger_type: item.trigger_type as SaveDraftInput["triggers"][number]["trigger_type"],
        connector_id: item.connector_id,
        routing_key: item.routing_key,
        actor_policy: item.actor_policy as SaveDraftInput["triggers"][number]["actor_policy"],
        service_account_user_id: item.service_account_user_id,
        enabled: item.enabled,
        config: {
          conversation_type: String(item.config.conversation_type ?? ""),
          require_mention: Boolean(item.config.require_mention),
          webhook_definition_id: String(
            item.config.webhook_definition_id ?? "",
          ),
        },
      })) ?? [],
    deliveries:
      draft?.deliveries.map((item) => ({
        delivery_type: item.delivery_type as SaveDraftInput["deliveries"][number]["delivery_type"],
        connector_id: item.connector_id,
        enabled: item.enabled,
        config: {
          target_reference: String(item.config.target_reference ?? ""),
          reply_mode: String(item.config.reply_mode ?? ""),
        },
      })) ?? [],
    capabilities: [],
  }
}

function changeTrigger(
  form: SaveDraftInput,
  setForm: (value: SaveDraftInput) => void,
  index: number,
  patch: Partial<SaveDraftInput["triggers"][number]>,
) {
  setForm({
    ...form,
    triggers: form.triggers.map((item, itemIndex) =>
      itemIndex === index ? { ...item, ...patch } : item,
    ),
  })
}

function changeDelivery(
  form: SaveDraftInput,
  setForm: (value: SaveDraftInput) => void,
  index: number,
  patch: Partial<SaveDraftInput["deliveries"][number]>,
) {
  setForm({
    ...form,
    deliveries: form.deliveries.map((item, itemIndex) =>
      itemIndex === index ? { ...item, ...patch } : item,
    ),
  })
}

function uniqueConnectors<T extends { id: string }>(values: T[]): T[] {
  return Array.from(new Map(values.map((item) => [item.id, item])).values())
}

function formatDate(value: string): string {
  if (!value) return "-"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

const selectClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
const textareaClass =
  "min-h-28 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
