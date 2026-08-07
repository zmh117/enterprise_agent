import { useState, type FormEvent } from "react"
import {
  AlertCircleIcon,
  ArrowLeftIcon,
  CheckCircle2Icon,
  Clock3Icon,
  GitBranchIcon,
  LoaderCircleIcon,
  PackageCheckIcon,
  PlusIcon,
  PowerIcon,
  SaveIcon,
  ShieldAlertIcon,
  Trash2Icon,
  WorkflowIcon,
} from "lucide-react"
import { Link, useParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  useActivatePublication,
  useApplication,
  useApplicationCatalog,
  useDeactivateLocalDeployment,
  usePublishDraft,
  useSaveDraft,
  useUpdateApplication,
  useValidateDraft,
} from "@/contexts/applications/application/business-application-queries"
import { useEligibleChannels } from "@/contexts/applications/application/managed-channel-queries"
import type {
  BusinessApplication,
  SaveDraftInput,
} from "@/contexts/applications/domain/business-application"
import { ApplicationState } from "@/contexts/applications/presentation/application-state"
import {
  MutationError,
  StatusBadge,
} from "@/contexts/applications/presentation/applications-page"
import {
  RuntimeOperationImpact,
  RuntimeReadinessPanel,
  RuntimeStatusBadge,
} from "@/contexts/applications/presentation/runtime-readiness"
import { cn } from "@/lib/utils"

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
  return (
    <ApplicationWorkspace key={query.data.revision} application={query.data} />
  )
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
          <RuntimeStatusBadge state={application} />
        </div>
      </header>

      <Tabs defaultValue="overview">
        <TabsList className="h-auto w-full justify-start overflow-x-auto">
          <TabsTrigger value="overview">概览</TabsTrigger>
          <TabsTrigger value="composition">组成配置</TabsTrigger>
          <TabsTrigger value="validation">校验结果</TabsTrigger>
          <TabsTrigger value="publications">发布与运行</TabsTrigger>
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
            ["工作流", draft?.workflow_publication_id || "未选择"],
          ]}
        />
        <SummaryCard
          title="控制面摘要"
          icon={PackageCheckIcon}
          rows={[
            ["发布数量", String(application.publications.length)],
            [
              "运行实例",
              String(
                application.deployments.filter((item) => item.active).length
              ),
            ],
            [
              "能力目录",
              application.capability_catalog_connected ? "已接入" : "未接入",
            ],
            [
              "数据面",
              application.runtime_status === "wired"
                ? "已接管"
                : application.runtime_status === "partially_wired"
                  ? "部分接管"
                  : application.runtime_status === "blocked"
                    ? "已阻塞"
                    : "未接管",
            ],
          ]}
        />
        <RuntimeReadinessPanel state={application} />
      </div>
    </div>
  )
}

function CompositionTab({ application }: { application: BusinessApplication }) {
  const catalog = useApplicationCatalog(application.code)
  const save = useSaveDraft(application.code)
  const draft = application.draft
  const [form, setForm] = useState<SaveDraftInput>(() =>
    draftToForm(application)
  )

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
          <Field label="Agent 发布版本" htmlFor="draft-agent">
            <select
              id="draft-agent"
              className={selectClass}
              required
              value={form.agent_publication_id}
              onChange={(event) =>
                setForm({
                  ...form,
                  agent_publication_id: event.target.value,
                  api_capability_release_ids: [],
                  builtin_tools: [],
                })
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
          <Field label="工作流发布版本（可选）" htmlFor="draft-workflow">
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
              <option value="">不引用工作流</option>
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
            流程设计画布不在本阶段实现；这里只固定已发布的工作流引用。
          </div>
        </CardContent>
      </Card>

      <PolicyEditor form={form} setForm={setForm} />
      <BindingsEditor form={form} setForm={setForm} catalog={catalog.data} />

      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>API Capability Allowlist</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!form.agent_publication_id ? (
            <div className="rounded-md border border-dashed p-4 text-sm leading-6 text-muted-foreground">
              请先选择 Agent 发布版本。应用不能配置 Agent Envelope 之外的
              Capability。
            </div>
          ) : !catalog.data?.capability_catalog_connected ? (
            <div className="rounded-md border border-dashed p-4 text-sm leading-6 text-muted-foreground">
              Capability 发布目录尚未接入，当前 Allowlist 必须为空。
            </div>
          ) : (
            <ApplicationCapabilitySelector
              releases={
                catalog.data.api_capabilities_by_agent_publication[
                  form.agent_publication_id
                ] ?? []
              }
              selected={form.api_capability_release_ids}
              onChange={(api_capability_release_ids) =>
                setForm({ ...form, api_capability_release_ids })
              }
            />
          )}
          {form.agent_publication_id &&
          catalog.data?.capability_catalog_connected &&
          (
            catalog.data.api_capabilities_by_agent_publication[
              form.agent_publication_id
            ] ?? []
          ).length === 0 ? (
            <div className="rounded-md border border-dashed p-4 text-sm leading-6 text-muted-foreground">
              所选 Agent 发布版本没有冻结任何 Capability，因此应用不能配置
              Capability。
            </div>
          ) : null}
        </CardContent>
      </Card>

      <BuiltinToolCompositionEditor
        form={form}
        setForm={setForm}
        catalog={catalog.data}
      />

      <MutationError error={save.error} />
      <div className="sticky bottom-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-background/95 p-3 shadow-lg backdrop-blur">
        <p className="text-xs text-muted-foreground">
          保存将基于 expected revision r{application.revision}{" "}
          创建新的追加式草稿。
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

function ApplicationCapabilitySelector({
  releases,
  selected,
  onChange,
}: {
  releases: Array<{
    identifier: string
    release_id: string
    description: string
    release_revision: number
    status: string
    release_note: string
    deprecation_reason: string
    replacement_release_id?: string | null
    selectable: boolean
  }>
  selected: string[]
  onChange: (value: string[]) => void
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm leading-6 text-muted-foreground">
        这里只展示所选 Agent Publication 已冻结的精确 Release。 Application
        Allowlist 是它的显式子集，不接受任意 Identifier 或版本输入。
      </p>
      <div className="grid gap-2 md:grid-cols-2">
        {releases.map((release) => {
          const checked = selected.includes(release.release_id)
          return (
            <label
              key={release.release_id}
              className={`flex items-start gap-3 rounded-md border p-3 text-sm ${
                release.selectable ? "" : "bg-muted/40"
              }`}
            >
              <Checkbox
                aria-label={`选择 Capability ${release.identifier}`}
                checked={checked}
                disabled={!release.selectable}
                onCheckedChange={(value) =>
                  onChange(
                    value
                      ? [...selected, release.release_id]
                      : selected.filter((item) => item !== release.release_id)
                  )
                }
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-medium break-all text-foreground">
                    {release.identifier}
                  </span>
                  <Badge variant="outline">
                    r{release.release_revision} · {release.status}
                  </Badge>
                </span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                  {release.description}
                </span>
                {release.release_note ? (
                  <span className="mt-1 block text-xs text-muted-foreground">
                    发布备注：{release.release_note}
                  </span>
                ) : null}
                {!release.selectable ? (
                  <span className="mt-1 block text-xs text-amber-700">
                    不兼容原因：Release 已为 {release.status}
                    {release.deprecation_reason
                      ? `（${release.deprecation_reason}）`
                      : ""}
                    ，新应用发布不能选择。
                  </span>
                ) : null}
              </span>
            </label>
          )
        })}
      </div>
      {selected
        .filter((id) => !releases.some((item) => item.release_id === id))
        .map((id) => (
          <div
            key={id}
            className="flex items-center justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
          >
            <span>
              不兼容原因：Release <span className="font-mono">{id}</span>{" "}
              不属于当前 Agent Publication Envelope。
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onChange(selected.filter((item) => item !== id))}
            >
              移除
            </Button>
          </div>
        ))}
    </div>
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
            <option value="channel">按渠道、发布版本与数据范围隔离</option>
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

type BuiltinToolMapping =
  SaveDraftInput["builtin_tools"][number]["resources"][number]
type TargetPath = SaveDraftInput["target_paths"][number]

function BuiltinToolCompositionEditor({
  form,
  setForm,
  catalog,
}: {
  form: SaveDraftInput
  setForm: (value: SaveDraftInput) => void
  catalog: Catalog
}) {
  const envelope =
    catalog?.builtin_tools_by_agent_publication[form.agent_publication_id] ?? []

  function toggleTarget(target: TargetPath) {
    const key = targetKey(target)
    const checked = form.target_paths.some((item) => targetKey(item) === key)
    const target_paths = checked
      ? form.target_paths.filter((item) => targetKey(item) !== key)
      : [...form.target_paths, target]
    setForm({ ...form, target_paths })
  }

  function toggleTool(toolReleaseId: string) {
    const checked = form.builtin_tools.some(
      (item) => item.tool_release_id === toolReleaseId
    )
    setForm({
      ...form,
      builtin_tools: checked
        ? form.builtin_tools.filter(
            (item) => item.tool_release_id !== toolReleaseId
          )
        : [
            ...form.builtin_tools,
            { tool_release_id: toolReleaseId, resources: [] },
          ],
    })
  }

  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>Built-in Tool Allowlist 与 Resource Mapping</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <p className="text-sm leading-6 text-muted-foreground">
          Application 只能选择当前 Agent Publication Envelope
          的显式子集；每个业务叶子目标必须为必需资源槽解析到唯一资源，cloud +
          edge 双候选则要求运行时 Tool Call 明确 placement。
        </p>
        {!form.agent_publication_id ? (
          <EmptyBinding text="请先选择 Agent Publication；应用不能自选 Identifier 或 Tool 版本。" />
        ) : (
          <>
            <section className="space-y-3 rounded-lg border p-4">
              <h3 className="text-sm font-medium">1. 业务叶子目标</h3>
              <p className="text-xs text-muted-foreground">
                目录只提供真实叶子：无基地环境、无车间基地，或具体车间；不会生成
                default/none 虚节点。
              </p>
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {(catalog?.target_paths ?? []).map((target) => {
                  const value: TargetPath = {
                    target_scope_type: target.target_scope_type,
                    environment_code: target.environment_code,
                    base_code: target.base_code,
                    workshop_code: target.workshop_code,
                  }
                  const checked = form.target_paths.some(
                    (item) => targetKey(item) === targetKey(value)
                  )
                  return (
                    <label
                      key={targetKey(value)}
                      className="flex items-start gap-3 rounded-md border p-3 text-sm"
                    >
                      <Checkbox
                        aria-label={`选择业务目标 ${targetPathLabel(value)}`}
                        checked={checked}
                        onCheckedChange={() => toggleTarget(value)}
                      />
                      <span>
                        <span className="block font-medium">
                          {target.display_name}
                        </span>
                        <span className="mt-1 block font-mono text-xs text-muted-foreground">
                          {targetPathLabel(value)}
                        </span>
                      </span>
                    </label>
                  )
                })}
              </div>
              {catalog?.target_paths.length === 0 ? (
                <EmptyBinding text="当前没有可用的真实叶子目标，请先在平台拓扑中配置环境/基地/车间。" />
              ) : null}
            </section>

            <section className="space-y-3 rounded-lg border p-4">
              <h3 className="text-sm font-medium">
                2. Agent Envelope 显式子集
              </h3>
              <div className="grid gap-2 md:grid-cols-2">
                {envelope.map((release) => {
                  const checked = form.builtin_tools.some(
                    (item) => item.tool_release_id === release.tool_release_id
                  )
                  return (
                    <label
                      key={release.tool_release_id}
                      className={cn(
                        "flex items-start gap-3 rounded-md border p-3 text-sm",
                        !release.selectable && "border-amber-300 bg-amber-50/60"
                      )}
                    >
                      <Checkbox
                        aria-label={`选择 Built-in Tool ${release.tool_identifier}`}
                        checked={checked}
                        disabled={!release.selectable && !checked}
                        onCheckedChange={() =>
                          toggleTool(release.tool_release_id)
                        }
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2 font-medium">
                          {release.display_name}
                          <Badge variant="outline">
                            r{release.release_revision} · Tool v
                            {release.tool_semantic_version}
                          </Badge>
                          <Badge
                            variant={
                              release.selectable ? "default" : "destructive"
                            }
                          >
                            {release.release_status} /{" "}
                            {release.installation_status}
                          </Badge>
                        </span>
                        <span className="mt-1 block font-mono text-xs text-muted-foreground">
                          {release.tool_identifier} · digest{" "}
                          {release.implementation_digest.slice(0, 12)}…
                        </span>
                      </span>
                    </label>
                  )
                })}
              </div>
              {!envelope.length ? (
                <EmptyBinding text="所选 Agent Publication 没有冻结 Built-in Tool Envelope。" />
              ) : null}
              {form.builtin_tools
                .filter(
                  (selection) =>
                    !envelope.some(
                      (item) =>
                        item.tool_release_id === selection.tool_release_id
                    )
                )
                .map((selection) => (
                  <div
                    key={selection.tool_release_id}
                    className="flex items-center justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
                  >
                    <span>
                      Release {selection.tool_release_id} 不属于当前 Agent
                      Envelope。
                    </span>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => toggleTool(selection.tool_release_id)}
                    >
                      移除
                    </Button>
                  </div>
                ))}
            </section>

            {form.builtin_tools.map((selection, toolIndex) => {
              const release = envelope.find(
                (item) => item.tool_release_id === selection.tool_release_id
              )
              if (!release || !catalog) return null
              return (
                <ToolResourceMappings
                  key={selection.tool_release_id}
                  form={form}
                  setForm={setForm}
                  catalog={catalog}
                  toolIndex={toolIndex}
                  release={release}
                />
              )
            })}

            <TargetMatrix form={form} catalog={catalog} envelope={envelope} />
          </>
        )}
      </CardContent>
    </Card>
  )
}

function ToolResourceMappings({
  form,
  setForm,
  catalog,
  toolIndex,
  release,
}: {
  form: SaveDraftInput
  setForm: (value: SaveDraftInput) => void
  catalog: NonNullable<Catalog>
  toolIndex: number
  release: NonNullable<Catalog>["builtin_tools_by_agent_publication"][string][number]
}) {
  const selection = form.builtin_tools[toolIndex]
  if (!selection) return null

  function updateMappings(resources: BuiltinToolMapping[]) {
    setForm({
      ...form,
      builtin_tools: form.builtin_tools.map((item, index) =>
        index === toolIndex ? { ...item, resources } : item
      ),
    })
  }

  function addMapping(slot: (typeof release.resource_slots)[number]) {
    const target = form.target_paths[0]
    if (!target) return
    updateMappings([
      ...selection.resources,
      {
        resource_slot: slot.code,
        target_scope_type: target.target_scope_type,
        environment_code: target.environment_code,
        base_code: target.base_code,
        workshop_code: target.workshop_code,
        placement: null,
        resource_revision_id: "",
        workshop_partition_policy_revision_id: "",
        loki_scope_policy_revision_id: "",
      },
    ])
  }

  return (
    <section className="space-y-4 rounded-lg border p-4">
      <div>
        <h3 className="font-medium">
          3. {release.display_name} Resource Mapping
        </h3>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {release.tool_identifier} · {release.tool_release_id}
        </p>
      </div>
      {!release.resource_slots.length ? (
        <EmptyBinding text="该 Tool Manifest 不声明 Resource Slot，无需映射资源。" />
      ) : null}
      {release.resource_slots.map((slot) => {
        const indexes = selection.resources.flatMap((mapping, index) =>
          mapping.resource_slot === slot.code ? [index] : []
        )
        return (
          <div key={slot.code} className="space-y-3 rounded-md bg-muted/25 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-medium">
                Slot: {slot.code} · {slot.resource_kind}
                {slot.required ? (
                  <Badge className="ml-2" variant="secondary">
                    必需
                  </Badge>
                ) : null}
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!form.target_paths.length}
                onClick={() => addMapping(slot)}
              >
                <PlusIcon />
                添加 Mapping
              </Button>
            </div>
            {indexes.map((mappingIndex) => (
              <MappingRow
                key={mappingIndex}
                mapping={selection.resources[mappingIndex]!}
                slot={slot}
                targets={form.target_paths}
                catalog={catalog}
                onChange={(next) =>
                  updateMappings(
                    selection.resources.map((item, index) =>
                      index === mappingIndex ? next : item
                    )
                  )
                }
                onRemove={() =>
                  updateMappings(
                    selection.resources.filter(
                      (_, index) => index !== mappingIndex
                    )
                  )
                }
              />
            ))}
            {!indexes.length ? (
              <EmptyBinding text="该 Slot 尚无 Resource Mapping。" />
            ) : null}
          </div>
        )
      })}
    </section>
  )
}

function MappingRow({
  mapping,
  slot,
  targets,
  catalog,
  onChange,
  onRemove,
}: {
  mapping: BuiltinToolMapping
  slot: {
    code: string
    resource_kind: "database" | "redis" | "loki"
    required: boolean
    allowed_scope_types: Array<"environment" | "base" | "workshop">
  }
  targets: TargetPath[]
  catalog: NonNullable<Catalog>
  onChange: (value: BuiltinToolMapping) => void
  onRemove: () => void
}) {
  const scopes = mappingScopes(targets, slot.resource_kind).filter((target) =>
    target.target_scope_type === "global"
      ? slot.resource_kind === "loki"
      : slot.allowed_scope_types.includes(target.target_scope_type)
  )
  const currentScopeKey = mappingScopeKey(mapping)
  const resourceOptions = catalog.resource_revisions.filter(
    (resource) =>
      resource.resource_kind === slot.resource_kind &&
      resourceCoversTarget(resource, mapping)
  )
  const workshopPolicies = catalog.workshop_policy_revisions.filter(
    (policy) =>
      mapping.target_scope_type === "workshop" &&
      policy.environment_code === mapping.environment_code &&
      policy.base_code === mapping.base_code &&
      policy.workshop_code === mapping.workshop_code &&
      (slot.resource_kind === "database"
        ? policy.database_rule_enabled
        : slot.resource_kind === "redis" && policy.redis_rule_enabled)
  )
  const lokiPolicies = catalog.loki_policy_revisions.filter(
    (policy) =>
      policy.resource_revision_id === mapping.resource_revision_id &&
      policy.environment_code === mapping.environment_code &&
      (!policy.base_code || policy.base_code === mapping.base_code)
  )
  return (
    <div className="space-y-3 rounded-md border bg-background p-3">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Field
          label="映射范围"
          htmlFor={`mapping-target-${slot.code}-${currentScopeKey}`}
        >
          <select
            id={`mapping-target-${slot.code}-${currentScopeKey}`}
            aria-label={`Mapping ${slot.code} 目标范围`}
            className={selectClass}
            value={currentScopeKey}
            onChange={(event) => {
              const target = scopes.find(
                (item) => mappingScopeKey(item) === event.target.value
              )
              if (!target) return
              onChange({
                ...mapping,
                ...target,
                resource_revision_id: "",
                workshop_partition_policy_revision_id: "",
                loki_scope_policy_revision_id: "",
              })
            }}
          >
            {scopes.map((target) => (
              <option
                key={mappingScopeKey(target)}
                value={mappingScopeKey(target)}
              >
                {mappingTargetLabel(target)}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Placement"
          htmlFor={`mapping-placement-${slot.code}-${currentScopeKey}`}
        >
          <select
            id={`mapping-placement-${slot.code}-${currentScopeKey}`}
            aria-label={`Mapping ${slot.code} Placement`}
            className={selectClass}
            value={mapping.placement ?? "none"}
            disabled={slot.resource_kind === "loki"}
            onChange={(event) =>
              onChange({
                ...mapping,
                placement:
                  event.target.value === "none"
                    ? null
                    : (event.target.value as "cloud" | "edge"),
              })
            }
          >
            <option value="none">无 placement</option>
            <option value="cloud">cloud</option>
            <option value="edge">edge</option>
          </select>
        </Field>
        <Field
          label="Published Resource Revision"
          htmlFor={`mapping-resource-${slot.code}-${currentScopeKey}`}
        >
          <select
            id={`mapping-resource-${slot.code}-${currentScopeKey}`}
            aria-label={`Mapping ${slot.code} Resource Revision`}
            className={selectClass}
            value={mapping.resource_revision_id}
            onChange={(event) =>
              onChange({
                ...mapping,
                resource_revision_id: event.target.value,
                loki_scope_policy_revision_id: "",
              })
            }
          >
            <option value="">请选择 Resource Revision</option>
            {resourceOptions.map((resource) => (
              <option
                key={resource.resource_revision_id}
                value={resource.resource_revision_id}
              >
                {resource.resource_name || resource.resource_code} · r
                {resource.resource_revision} · {resource.scope_type}
              </option>
            ))}
          </select>
        </Field>
        {slot.resource_kind === "loki" ? (
          <Field
            label="Loki Scope Policy"
            htmlFor={`mapping-policy-${slot.code}-${currentScopeKey}`}
          >
            <select
              id={`mapping-policy-${slot.code}-${currentScopeKey}`}
              aria-label={`Mapping ${slot.code} Loki Policy`}
              className={selectClass}
              value={mapping.loki_scope_policy_revision_id}
              onChange={(event) =>
                onChange({
                  ...mapping,
                  loki_scope_policy_revision_id: event.target.value,
                })
              }
            >
              <option value="">请选择 Published Policy</option>
              {lokiPolicies.map((policy) => (
                <option
                  key={policy.policy_revision_id}
                  value={policy.policy_revision_id}
                >
                  {policy.policy_code} · r{policy.policy_revision} ·{" "}
                  {policy.health_status}
                </option>
              ))}
            </select>
          </Field>
        ) : mapping.target_scope_type === "workshop" ? (
          <Field
            label="Workshop Partition Policy"
            htmlFor={`mapping-policy-${slot.code}-${currentScopeKey}`}
          >
            <select
              id={`mapping-policy-${slot.code}-${currentScopeKey}`}
              aria-label={`Mapping ${slot.code} Workshop Policy`}
              className={selectClass}
              value={mapping.workshop_partition_policy_revision_id}
              onChange={(event) =>
                onChange({
                  ...mapping,
                  workshop_partition_policy_revision_id: event.target.value,
                })
              }
            >
              <option value="">请选择 Published Policy</option>
              {workshopPolicies.map((policy) => (
                <option
                  key={policy.policy_revision_id}
                  value={policy.policy_revision_id}
                >
                  {policy.policy_code} · r{policy.policy_revision}
                </option>
              ))}
            </select>
          </Field>
        ) : null}
      </div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          候选资源 {resourceOptions.length} 个；策略选项{" "}
          {slot.resource_kind === "loki"
            ? lokiPolicies.length
            : workshopPolicies.length}{" "}
          个。
        </p>
        <Button
          type="button"
          size="sm"
          variant="destructive"
          onClick={onRemove}
        >
          <Trash2Icon />
          删除 Mapping
        </Button>
      </div>
    </div>
  )
}

function TargetMatrix({
  form,
  catalog,
  envelope,
}: {
  form: SaveDraftInput
  catalog: Catalog
  envelope: NonNullable<Catalog>["builtin_tools_by_agent_publication"][string]
}) {
  const rows = form.builtin_tools.flatMap((selection) => {
    const release = envelope.find(
      (item) => item.tool_release_id === selection.tool_release_id
    )
    if (!release) return []
    return release.resource_slots.flatMap((slot) =>
      form.target_paths.map((target) => {
        const candidates = selection.resources.filter(
          (mapping) =>
            mapping.resource_slot === slot.code &&
            mappingCoversTarget(mapping, target)
        )
        return {
          release,
          slot,
          target,
          candidates,
          result: matrixResult(candidates, slot.resource_kind, catalog),
        }
      })
    )
  })
  return (
    <section className="space-y-3 rounded-lg border p-4">
      <div>
        <h3 className="text-sm font-medium">4. 有限目标矩阵预检</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          这是保存前提示；后端发布仍会以精确 Revision、Scope、Policy 与 hash
          重新展开并失败关闭。
        </p>
      </div>
      {!rows.length ? (
        <EmptyBinding text="选择带资源槽的 Tool 和至少一个业务目标后生成矩阵。" />
      ) : (
        <div className="space-y-2">
          {rows.map((row) => (
            <div
              key={`${row.release.tool_release_id}:${row.slot.code}:${targetKey(row.target)}`}
              className="grid gap-2 rounded-md border p-3 text-xs md:grid-cols-[1fr_1fr_8rem] md:items-center"
            >
              <div>
                <span className="font-medium">
                  {row.release.tool_identifier} · {row.slot.code}
                </span>
                <span className="mt-1 block font-mono text-muted-foreground">
                  {targetPathLabel(row.target)}
                </span>
              </div>
              <div className="text-muted-foreground">
                候选 {row.candidates.length}：
                {row.candidates
                  .map((item) => item.placement ?? "none")
                  .join(" / ") || "无"}
              </div>
              <Badge variant={row.result.variant}>{row.result.label}</Badge>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function matrixResult(
  candidates: BuiltinToolMapping[],
  resourceKind: "database" | "redis" | "loki",
  catalog: Catalog
): { label: string; variant: "default" | "secondary" | "destructive" } {
  if (!candidates.length) return { label: "缺失", variant: "destructive" }
  const incomplete = candidates.some((mapping) => {
    if (!mapping.resource_revision_id) return true
    if (resourceKind === "loki") return !mapping.loki_scope_policy_revision_id
    return (
      mapping.target_scope_type === "workshop" &&
      !mapping.workshop_partition_policy_revision_id
    )
  })
  if (incomplete) return { label: "映射未完整", variant: "destructive" }
  const groups = new Map<string, number>()
  for (const candidate of candidates) {
    const key = candidate.placement ?? "none"
    groups.set(key, (groups.get(key) ?? 0) + 1)
  }
  if (
    [...groups.values()].some((count) => count > 1) ||
    (groups.has("none") && groups.size > 1)
  ) {
    return { label: "范围重叠", variant: "destructive" }
  }
  if (groups.has("cloud") && groups.has("edge")) {
    const policyIds = new Set(
      candidates.map((item) => item.workshop_partition_policy_revision_id)
    )
    if (resourceKind !== "loki" && policyIds.size > 1) {
      return { label: "策略不一致", variant: "destructive" }
    }
    return { label: "运行时须选 placement", variant: "secondary" }
  }
  const selectedResourceExists = candidates.every((mapping) =>
    catalog?.resource_revisions.some(
      (resource) =>
        resource.resource_revision_id === mapping.resource_revision_id
    )
  )
  return selectedResourceExists
    ? { label: "唯一解析", variant: "default" }
    : { label: "资源已不可用", variant: "destructive" }
}

function mappingScopes(
  targets: TargetPath[],
  resourceKind: "database" | "redis" | "loki"
): BuiltinToolMapping[] {
  const emptyMapping: BuiltinToolMapping = {
    resource_slot: "",
    target_scope_type: "global",
    environment_code: "",
    base_code: "",
    workshop_code: "",
    placement: null,
    resource_revision_id: "",
    workshop_partition_policy_revision_id: "",
    loki_scope_policy_revision_id: "",
  }
  const values: BuiltinToolMapping[] =
    resourceKind === "loki" ? [emptyMapping] : []
  for (const target of targets) {
    if (resourceKind === "loki") {
      values.push({
        ...emptyMapping,
        target_scope_type: "environment",
        environment_code: target.environment_code,
      })
      if (target.base_code) {
        values.push({
          ...emptyMapping,
          target_scope_type: "base",
          environment_code: target.environment_code,
          base_code: target.base_code,
        })
      }
    } else {
      values.push({
        ...emptyMapping,
        target_scope_type: target.target_scope_type,
        environment_code: target.environment_code,
        base_code: target.base_code,
        workshop_code: target.workshop_code,
      })
    }
  }
  return [
    ...new Map(values.map((item) => [mappingScopeKey(item), item])).values(),
  ]
}

function targetKey(target: TargetPath) {
  return `${target.target_scope_type}:${target.environment_code}:${target.base_code}:${target.workshop_code}`
}

function mappingScopeKey(
  target: Pick<
    BuiltinToolMapping,
    "target_scope_type" | "environment_code" | "base_code" | "workshop_code"
  >
) {
  return `${target.target_scope_type}:${target.environment_code}:${target.base_code}:${target.workshop_code}`
}

function targetPathLabel(target: TargetPath) {
  return [target.environment_code, target.base_code, target.workshop_code]
    .filter(Boolean)
    .join(" / ")
}

function mappingTargetLabel(
  target: Pick<
    BuiltinToolMapping,
    "target_scope_type" | "environment_code" | "base_code" | "workshop_code"
  >
) {
  return target.target_scope_type === "global"
    ? "global"
    : `${target.target_scope_type} · ${[target.environment_code, target.base_code, target.workshop_code].filter(Boolean).join(" / ")}`
}

function mappingCoversTarget(mapping: BuiltinToolMapping, target: TargetPath) {
  if (mapping.target_scope_type === "global") return true
  if (mapping.environment_code !== target.environment_code) return false
  if (mapping.target_scope_type === "environment") return true
  if (mapping.base_code !== target.base_code) return false
  if (mapping.target_scope_type === "base") return true
  return mapping.workshop_code === target.workshop_code
}

function resourceCoversTarget(
  resource: NonNullable<Catalog>["resource_revisions"][number],
  target: Pick<
    BuiltinToolMapping,
    "target_scope_type" | "environment_code" | "base_code" | "workshop_code"
  >
) {
  if (target.target_scope_type === "global")
    return resource.scope_type === "global"
  if (resource.scope_type === "global") return true
  if (resource.environment_code !== target.environment_code) return false
  if (resource.scope_type === "environment") return true
  if (resource.base_code !== target.base_code) return false
  if (resource.scope_type === "base")
    return (
      target.target_scope_type === "base" ||
      target.target_scope_type === "workshop"
    )
  return (
    target.target_scope_type === "workshop" &&
    resource.workshop_code === target.workshop_code
  )
}

function BindingsEditor({
  form,
  setForm,
  catalog,
}: {
  form: SaveDraftInput
  setForm: (value: SaveDraftInput) => void
  catalog: Catalog
}) {
  const delivery = uniqueConnectors(
    catalog?.connectors.filter((item) => item.direction === "delivery") ?? []
  )
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card className="shadow-none">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>触发器绑定</CardTitle>
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
                    connector_id: "",
                    routing_key: "bot:",
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
            添加触发器
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {form.triggers.length === 0 ? (
            <EmptyBinding text="尚未配置触发器；应用可以发布，但不会产生入口路由。" />
          ) : null}
          {form.triggers.map((trigger, index) => (
            <div key={index} className="space-y-3 rounded-lg border p-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field
                  label={`触发器 ${index + 1} 类型`}
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
                        routing_key:
                          type === "dingtalk_private"
                            ? "bot:"
                            : type === "dingtalk_group"
                              ? "conversation:"
                              : trigger.routing_key,
                        actor_policy:
                          type === "webhook"
                            ? "SERVICE_ACCOUNT"
                            : "CURRENT_SENDER",
                        connector_id: "",
                        config: {
                          ...trigger.config,
                          conversation_type:
                            type === "dingtalk_private"
                              ? "private"
                              : type === "dingtalk_group"
                                ? "group"
                                : "webhook",
                          require_mention: type === "dingtalk_group",
                          webhook_definition_id: "",
                        },
                      })
                    }}
                  >
                    <option value="dingtalk_private">钉钉私聊</option>
                    <option value="dingtalk_group">钉钉群聊</option>
                    <option value="webhook">Webhook</option>
                  </select>
                </Field>
                <Field label="入口渠道" htmlFor={`trigger-connector-${index}`}>
                  <EligibleChannelSelect
                    id={`trigger-connector-${index}`}
                    trigger={trigger}
                    onChange={(change) =>
                      changeTrigger(form, setForm, index, change)
                    }
                  />
                </Field>
                <Field
                  label="路由键（Routing Key）"
                  htmlFor={`trigger-route-${index}`}
                >
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
                  <p className="text-xs leading-5 text-muted-foreground">
                    {trigger.trigger_type === "dingtalk_private"
                      ? "私聊使用 bot:<robot identity>；同一机器人下所有用户共享入口匹配，但权限仍按当前发送人。"
                      : trigger.trigger_type === "dingtalk_group"
                        ? "群聊使用 conversation:<open conversation id>；不要填写用户 ID 或消息内容。"
                        : "Webhook 路由由对应触发器定义控制。"}
                    {isLegacyRoutingKey(
                      trigger.trigger_type,
                      trigger.routing_key
                    )
                      ? " 当前是旧路由键，必须改为带命名空间的新值并重新发布。"
                      : ""}
                  </p>
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
                删除触发器
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="shadow-none">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>投递绑定</CardTitle>
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
            添加投递
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {form.deliveries.length === 0 ? (
            <EmptyBinding text="尚未配置投递；发布不会改变现有结果投递链。" />
          ) : null}
          {form.deliveries.map((binding, index) => (
            <div key={index} className="space-y-3 rounded-lg border p-3">
              <Field
                label={`投递 ${index + 1} 类型`}
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
              <Field label="投递连接器" htmlFor={`delivery-connector-${index}`}>
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
                    ? uniqueConnectors(
                        catalog?.connectors.filter(
                          (item) => item.direction === "ingress"
                        ) ?? []
                      )
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
                      (_, item) => item !== index
                    ),
                  })
                }
              >
                删除投递
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

function EligibleChannelSelect({
  id,
  trigger,
  onChange,
}: {
  id: string
  trigger: SaveDraftInput["triggers"][number]
  onChange: (patch: Partial<SaveDraftInput["triggers"][number]>) => void
}) {
  const query = useEligibleChannels(trigger.trigger_type)
  const items = query.data ?? []
  const current = items.find(
    (item) =>
      (trigger.config.webhook_definition_id &&
        item.webhook_trigger_id === trigger.config.webhook_definition_id) ||
      (!trigger.config.webhook_definition_id &&
        item.id === trigger.connector_id)
  )
  const selected = current
    ? (current.webhook_trigger_id ?? current.id)
    : trigger.config.webhook_definition_id || trigger.connector_id
  const invalid = Boolean(selected) && !current

  return (
    <>
      <select
        id={id}
        className={selectClass}
        value={selected}
        disabled={query.isLoading}
        onChange={(event) => {
          const item = items.find(
            (candidate) =>
              (candidate.webhook_trigger_id ?? candidate.id) ===
              event.target.value
          )
          if (!item) {
            onChange({
              connector_id: "",
              config: {
                ...trigger.config,
                webhook_definition_id: "",
              },
            })
            return
          }
          onChange({
            connector_id: item.id,
            routing_key:
              trigger.trigger_type === "webhook"
                ? item.routing_key || trigger.routing_key
                : trigger.routing_key,
            config: {
              ...trigger.config,
              webhook_definition_id:
                trigger.trigger_type === "webhook"
                  ? item.webhook_trigger_id || ""
                  : "",
            },
          })
        }}
      >
        <option value="">
          {query.isLoading ? "正在加载可用渠道…" : "请选择已启用渠道"}
        </option>
        {invalid ? (
          <option value={selected}>
            当前绑定已停用或失效 · {trigger.connector_id}
          </option>
        ) : null}
        {items.map((item) => (
          <option
            key={`${item.kind}-${item.webhook_trigger_id ?? item.id}`}
            value={item.webhook_trigger_id ?? item.id}
          >
            {item.name} ·{" "}
            {item.kind === "WEBHOOK" ? "Webhook" : "钉钉应用机器人"}
          </option>
        ))}
      </select>
      {query.isError ? (
        <p className="text-xs text-destructive">
          无法加载可用渠道，请刷新后重试。
        </p>
      ) : invalid ? (
        <p className="text-xs text-amber-700">
          该旧绑定不再满足入口条件；保存前请选择新的可用渠道。
        </p>
      ) : null}
    </>
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
                    <li
                      key={`${item.field}-${index}`}
                      className="rounded border bg-white/60 p-2"
                    >
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
                canPublish
                  ? "创建不可变发布"
                  : "必须先通过校验且应用处于启用状态"
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
          ["Agent 发布版本", revision?.agent_publication_id || "未选择"],
          ["工作流发布版本", revision?.workflow_publication_id || "可选"],
          ["触发器", String(revision?.triggers.length ?? 0)],
          ["投递", String(revision?.deliveries.length ?? 0)],
          ["能力", String(revision?.capabilities.length ?? 0)],
        ]}
      />
    </div>
  )
}

function PublicationTab({ application }: { application: BusinessApplication }) {
  const activate = useActivatePublication(application.code)
  const deactivate = useDeactivateLocalDeployment(application.code)
  const environment = "local"
  const deployment = application.deployments.find(
    (item) => item.environment === environment
  )
  const error = activate.error ?? deactivate.error
  return (
    <div className="space-y-5">
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>本地部署</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border bg-muted/30 p-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">唯一运行环境</Badge>
              <span className="font-mono">local</span>
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              发布、激活、回退和停用都直接作用于当前本地运行实例，不再维护
              test、staging 或 production 部署。
            </p>
          </div>
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
          <RuntimeOperationImpact
            state={deployment ?? application}
            action="deactivate"
            targetEnvironment={environment}
          />
          {deployment?.active ? (
            <Button
              type="button"
              variant="destructive"
              disabled={deactivate.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    "确认停用 local 环境？后续新消息若没有匹配应用，将返回配置错误且不创建任务；已入队任务继续使用原版本。"
                  )
                ) {
                  deactivate.mutate({
                    expectedRevision: deployment.revision,
                  })
                }
              }}
            >
              <PowerIcon aria-hidden="true" />
              停用 local
            </Button>
          ) : null}
          <MutationError error={error} />
          <p className="text-xs leading-5 text-muted-foreground">
            状态由服务端按数据面闸门、本地运行实例和发布版本
            组件统一计算；界面不自行猜测是否接管。
          </p>
        </CardContent>
      </Card>

      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>发布历史</CardTitle>
        </CardHeader>
        <CardContent>
          {application.publications.length === 0 ? (
            <EmptyBinding text="尚无 publication。先在校验页发布一个合法草稿。" />
          ) : (
            <div className="space-y-3">
              {application.publications.map((publication) => (
                <article
                  key={publication.id}
                  data-testid="publication-history-card"
                  className="grid gap-4 rounded-lg border p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-start gap-2">
                      <Badge variant="outline" className="shrink-0">
                        r{publication.revision}
                      </Badge>
                      <span className="min-w-0 font-mono text-sm leading-5 font-medium break-all">
                        {publication.id}
                      </span>
                    </div>
                    <dl className="mt-4 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
                      <PublicationMetadata
                        label="配置哈希"
                        value={`${publication.config_hash.slice(0, 16)}…`}
                        monospace
                      />
                      <PublicationMetadata
                        label="发布人"
                        value={publication.published_by}
                        monospace
                      />
                      <PublicationMetadata
                        label="发布时间"
                        value={formatDate(publication.published_at)}
                      />
                      <PublicationMetadata
                        label="结构版本"
                        value={`v${publication.schema_version}`}
                      />
                    </dl>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full sm:w-auto"
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
                          `确认将发布版本 r${publication.revision} ${action}到 local 环境？匹配入口会使用该版本；未命中消息将返回配置错误且不创建任务，已入队任务不切换版本。`
                        )
                      ) {
                        activate.mutate({
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
                  <div className="sm:col-span-2">
                    <RuntimeOperationImpact
                      state={publication}
                      action={
                        deployment?.active &&
                        deployment.publication_id !== publication.id
                          ? "rollback"
                          : "activate"
                      }
                      targetEnvironment={environment}
                    />
                  </div>
                </article>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function PublicationMetadata({
  label,
  value,
  monospace = false,
}: {
  label: string
  value: string
  monospace?: boolean
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-1 leading-5 break-words text-foreground",
          monospace && "font-mono break-all"
        )}
        title={value}
      >
        {value}
      </dd>
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
              <dd
                className="min-w-0 truncate text-right font-medium"
                title={value}
              >
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
      conversation_mode: "channel",
      recent_message_limit: Number(
        draft?.session_policy.recent_message_limit ?? 20
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
        trigger_type:
          item.trigger_type as SaveDraftInput["triggers"][number]["trigger_type"],
        connector_id: item.connector_id,
        routing_key: item.routing_key,
        actor_policy:
          item.actor_policy as SaveDraftInput["triggers"][number]["actor_policy"],
        service_account_user_id: item.service_account_user_id,
        enabled: item.enabled,
        config: {
          conversation_type: String(item.config.conversation_type ?? ""),
          require_mention: Boolean(item.config.require_mention),
          webhook_definition_id: String(
            item.config.webhook_definition_id ?? ""
          ),
        },
      })) ?? [],
    deliveries:
      draft?.deliveries.map((item) => ({
        delivery_type:
          item.delivery_type as SaveDraftInput["deliveries"][number]["delivery_type"],
        connector_id: item.connector_id,
        enabled: item.enabled,
        config: {
          target_reference: String(item.config.target_reference ?? ""),
          reply_mode: String(item.config.reply_mode ?? ""),
        },
      })) ?? [],
    capabilities:
      draft?.capabilities.map((item) => ({
        capability_code: item.capability_code,
        version_constraint: item.version_constraint,
        enabled: item.enabled,
      })) ?? [],
    api_capability_release_ids: draft?.api_capability_release_ids ?? [],
    builtin_tools:
      draft?.builtin_tools.map((tool) => ({
        tool_release_id: tool.tool_release_id,
        resources: tool.resources.map((mapping) => ({
          resource_slot: mapping.resource_slot,
          target_scope_type: mapping.target_scope_type,
          environment_code: mapping.environment_code,
          base_code: mapping.base_code,
          workshop_code: mapping.workshop_code,
          placement: mapping.placement ?? null,
          resource_revision_id: mapping.resource_revision_id,
          workshop_partition_policy_revision_id:
            mapping.workshop_partition_policy_revision_id,
          loki_scope_policy_revision_id: mapping.loki_scope_policy_revision_id,
        })),
      })) ?? [],
    target_paths:
      draft?.target_paths.map((target) => ({
        target_scope_type: target.target_scope_type,
        environment_code: target.environment_code,
        base_code: target.base_code,
        workshop_code: target.workshop_code,
      })) ?? [],
  }
}

function changeTrigger(
  form: SaveDraftInput,
  setForm: (value: SaveDraftInput) => void,
  index: number,
  patch: Partial<SaveDraftInput["triggers"][number]>
) {
  setForm({
    ...form,
    triggers: form.triggers.map((item, itemIndex) =>
      itemIndex === index ? { ...item, ...patch } : item
    ),
  })
}

function changeDelivery(
  form: SaveDraftInput,
  setForm: (value: SaveDraftInput) => void,
  index: number,
  patch: Partial<SaveDraftInput["deliveries"][number]>
) {
  setForm({
    ...form,
    deliveries: form.deliveries.map((item, itemIndex) =>
      itemIndex === index ? { ...item, ...patch } : item
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

function isLegacyRoutingKey(triggerType: string, routingKey: string): boolean {
  const value = routingKey.trim().toLowerCase()
  if (triggerType === "dingtalk_private") {
    return !value.startsWith("bot:") || value === "bot:"
  }
  if (triggerType === "dingtalk_group") {
    return !value.startsWith("conversation:") || value === "conversation:"
  }
  return false
}

const selectClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
const textareaClass =
  "min-h-28 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
