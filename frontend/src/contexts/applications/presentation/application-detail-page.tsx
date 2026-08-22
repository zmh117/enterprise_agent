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
import { useFileOperations } from "@/contexts/operations/application/runtime-record-queries"
import type { FileOperations } from "@/contexts/operations/domain/runtime-record"
import { cn } from "@/lib/utils"

const FILE_MCP_READ_TOOL_IDS = [
  "task_workspace_get",
  "task_workspace_list_files",
  "file_get_metadata",
  "file_prepare_materialization",
] as const
const FILE_MCP_EDIT_TOOL_IDS = ["file_create_commit_intent"] as const
const FILE_MCP_DELIVERY_TOOL_IDS = ["file_deliver_version"] as const

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
            [
              "工作区周期",
              draft?.task_workspace_retention_period ?? "WEEK（新草稿默认）",
            ],
            ["任务文件能力", formatTaskFileFeatures(draft?.task_file_features)],
            ["直接文本文件规则", "TXT/Markdown 可读写，LOG 只读"],
            [
              "文档解析/OCR",
              formatDocumentProcessingSelection(
                draft?.document_processing_profile_code
              ),
            ],
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
            ["MCP 工具", String(draft?.mcp_tools.length ?? 0)],
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
                  mcp_tools: [],
                })
              }
            >
              <option value="">请选择已发布 Agent</option>
              {catalog.data?.agents
                .filter((item) => item.runtime_kind === "python-v1")
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.code} · r{item.revision} ·{" "}
                    {applicationRuntimeLabel(item.runtime_kind)}
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

      <PolicyEditor form={form} setForm={setForm} catalog={catalog.data} />
      <BindingsEditor form={form} setForm={setForm} catalog={catalog.data} />

      <McpToolSelector form={form} setForm={setForm} catalog={catalog.data} />

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

function PolicyEditor({
  form,
  setForm,
  catalog,
}: {
  form: SaveDraftInput
  setForm: (value: SaveDraftInput) => void
  catalog: Catalog
}) {
  const availableFileTools = new Set(
    (catalog?.mcp_tools_by_agent_publication[form.agent_publication_id] ?? [])
      .filter((tool) => tool.server_code === "file-service")
      .map((tool) => tool.tool_identifier)
  )
  const missingRequiredFileTools = [
    ...requiredFileMcpToolIds(form.task_file_features),
  ].filter((identifier) => !availableFileTools.has(identifier))
  const selectedAgent = catalog?.agents.find(
    (item) => item.id === form.agent_publication_id
  )
  const fileContextRuntimeCompatible =
    selectedAgent?.runtime_protocol_versions.includes("1.3") === true
  const selectedDocumentProfile = catalog?.document_processing_profiles.find(
    (item) => item.code === form.document_processing_profile_code
  )
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>会话与执行策略</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Field
          label="任务工作区保留周期"
          htmlFor="policy-task-workspace-retention"
        >
          <select
            id="policy-task-workspace-retention"
            className={selectClass}
            value={form.task_workspace_retention_period}
            onChange={(event) =>
              setForm({
                ...form,
                task_workspace_retention_period: event.target
                  .value as SaveDraftInput["task_workspace_retention_period"],
              })
            }
          >
            <option value="DAY">当日（次日 00:00 到期）</option>
            <option value="WEEK">当周（下周一 00:00 到期）</option>
            <option value="MONTH">当月（下月一日 00:00 到期）</option>
          </select>
          <p className="text-xs leading-5 text-muted-foreground">
            来源：当前草稿。按 Asia/Shanghai
            自然周期固定到期，活动不会滚动延期；不影响聊天附件的 360 天保留。
          </p>
        </Field>
        <Field label="直接文本文件规则">
          <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
            TXT/Markdown 可读写，LOG 只读
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            TXT、LOG、Markdown 由 Agent 通过任务工作区直接读取，不进入
            Docling。该规则由平台固定，不属于应用 Publication 配置；Markdown
            始终按不可信纯文本处理，不在管理端渲染。
          </p>
          {!fileContextRuntimeCompatible ? (
            <p className="text-xs leading-5 text-destructive">
              所选 Agent 发布版本未声明支持 Runtime protocol v1.3。
            </p>
          ) : null}
        </Field>
        <Field
          label="文档解析/OCR Profile"
          htmlFor="policy-document-processing"
        >
          <select
            id="policy-document-processing"
            className={selectClass}
            value={form.document_processing_profile_code}
            onChange={(event) => {
              const profile = event.target
                .value as SaveDraftInput["document_processing_profile_code"]
              const taskFileFeatures =
                profile !== "NONE"
                  ? {
                      ...form.task_file_features,
                      workspace_enabled: true,
                      file_mcp_enabled: true,
                    }
                  : form.task_file_features
              setForm({
                ...form,
                document_processing_profile_code: profile,
                task_file_features: taskFileFeatures,
                mcp_tools: selectRequiredFileMcpTools(
                  form.mcp_tools,
                  taskFileFeatures,
                  availableFileTools
                ),
                session_policy:
                  profile !== "NONE"
                    ? {
                        ...form.session_policy,
                        attachments_enabled: true,
                        continuous_conversation_enabled: true,
                      }
                    : form.session_policy,
              })
            }}
          >
            {(catalog?.document_processing_profiles.length
              ? catalog.document_processing_profiles
              : [
                  {
                    code: "NONE" as const,
                    label: "关闭文档处理",
                  },
                ]
            ).map((profile) => (
              <option
                key={profile.code}
                value={profile.code}
                disabled={"selectable" in profile && profile.selectable === false}
              >
                {profile.label}
              </option>
            ))}
          </select>
          <p className="text-xs leading-5 text-muted-foreground">
            仅可选择平台代码发布的固定 Profile；发布后冻结 code、version 与
            hash。PDF、DOCX、PPTX、XLSX 和图片通过 Docling
            生成只读文字表示，再由 Agent 读取；不能填写 Docling
            URL、模型、插件或原始 options。
          </p>
          {selectedDocumentProfile?.code !== undefined &&
          selectedDocumentProfile.code !== "NONE" ? (
            <div className="space-y-1">
              <p className="text-xs leading-5 text-muted-foreground">
                当前选择：除正文与表格外，对 DOCX/PPTX 原始内嵌图片提取文字、阅读顺序、0..10000 坐标和有限几何关系；仅在上游提供时显示置信度，否则明确标注为未提供。仅应用图片自身 EXIF 方向，不应用 Office 显示裁剪、旋转或翻转，因此可能提取页面上已裁掉的区域。它不是 VLM，不识别箭头、颜色、图标、照片含义或因果；OCR 内容始终是不可信文件数据。
                真实运行状态请到“发布与运行”查看。
              </p>
              {!fileContextRuntimeCompatible ? (
                <p className="text-xs leading-5 text-destructive">
                  所选 Agent 发布版本未声明支持 Runtime protocol
                  v1.3，不能发布 Docling 文件上下文。
                </p>
              ) : null}
            </div>
          ) : null}
        </Field>
        <div className="space-y-3 rounded-md border p-4 md:col-span-2 xl:col-span-2">
          <div>
            <p className="text-sm font-medium">任务文件灰度功能</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              来源：当前草稿；发布后冻结到 Publication Revision。未启用的 Job
              保持原行为。
            </p>
          </div>
          {(
            [
              ["workspace_enabled", "任务工作区"],
              ["file_mcp_enabled", "File MCP"],
              ["runtime_file_edit_enabled", "Runtime Write/Edit"],
              ["default_file_delivery_enabled", "默认文件交付"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="flex items-center gap-3 text-sm">
              <Checkbox
                checked={form.task_file_features[key]}
                onCheckedChange={(checked) => {
                  const taskFileFeatures = nextTaskFileFeatures(
                    form.task_file_features,
                    key,
                    checked === true
                  )
                  setForm({
                    ...form,
                    task_file_features: taskFileFeatures,
                    mcp_tools: selectRequiredFileMcpTools(
                      form.mcp_tools,
                      taskFileFeatures,
                      availableFileTools
                    ),
                    session_policy: taskFileFeatures.workspace_enabled
                      ? {
                          ...form.session_policy,
                          attachments_enabled: true,
                          continuous_conversation_enabled: true,
                        }
                      : form.session_policy,
                  })
                }}
              />
              {label}
            </label>
          ))}
          {missingRequiredFileTools.length ? (
            <p className="text-xs leading-5 text-destructive md:col-span-2 xl:col-span-2">
              当前 Agent 发布版本缺少任务文件工具，请先在 Agent 管理中发布包含
              File MCP 工具的新版本，再回到这里选择并发布业务应用。
            </p>
          ) : null}
        </div>
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
        <div className="space-y-3 rounded-md border p-4 md:col-span-2 xl:col-span-3">
          <p className="text-sm font-medium">会话能力</p>
          <label className="flex items-start gap-3 text-sm">
            <Checkbox
              aria-label="连续会话"
              checked={form.session_policy.continuous_conversation_enabled}
              disabled={form.task_file_features.workspace_enabled}
              onCheckedChange={(checked) =>
                setForm({
                  ...form,
                  session_policy: {
                    ...form.session_policy,
                    continuous_conversation_enabled: checked === true,
                  },
                })
              }
            />
            <span>
              连续会话
              <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                允许同一渠道会话在后续消息中继续使用已保存的会话上下文；任务工作区启用时必须开启。
              </span>
            </span>
          </label>
          <label className="flex items-start gap-3 text-sm">
            <Checkbox
              aria-label="允许消息附件"
              checked={form.session_policy.attachments_enabled}
              disabled={form.task_file_features.workspace_enabled}
              onCheckedChange={(checked) =>
                setForm({
                  ...form,
                  session_policy: {
                    ...form.session_policy,
                    attachments_enabled: checked === true,
                  },
                })
              }
            />
            <span>
              允许消息附件
              <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                控制钉钉入站附件处理；任务工作区启用时此项必须开启，需先关闭任务工作区才能关闭。
              </span>
            </span>
          </label>
        </div>
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

function McpToolSelector({
  form,
  setForm,
  catalog,
}: {
  form: SaveDraftInput
  setForm: (value: SaveDraftInput) => void
  catalog: Catalog
}) {
  const envelope =
    catalog?.mcp_tools_by_agent_publication[form.agent_publication_id] ?? []
  const requiredFileTools = requiredFileMcpToolIds(form.task_file_features)

  function toggle(identifier: string) {
    if (requiredFileTools.has(identifier)) return
    setForm({
      ...form,
      mcp_tools: form.mcp_tools.includes(identifier)
        ? form.mcp_tools.filter((item) => item !== identifier)
        : [...form.mcp_tools, identifier],
    })
  }

  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>MCP Tool 显式子集</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-6 text-muted-foreground">
          应用只能选择 Agent 发布版本已经冻结的 MCP 工具。资源不在应用中做
          Mapping；实际调用时根据 Job 目标唯一解析已发布 Tool Resource。
        </p>
        {!form.agent_publication_id ? (
          <EmptyBinding text="请先选择 Agent 发布版本。" />
        ) : !envelope.length ? (
          <EmptyBinding text="所选 Agent 发布版本没有 MCP Tool。" />
        ) : (
          <div className="grid gap-2 md:grid-cols-2">
            {envelope.map((tool) => (
              <label
                key={tool.tool_identifier}
                className="flex items-start gap-3 rounded-md border p-3 text-sm"
              >
                <Checkbox
                  aria-label={`选择 MCP Tool ${tool.tool_identifier}`}
                  checked={form.mcp_tools.includes(tool.tool_identifier)}
                  disabled={requiredFileTools.has(tool.tool_identifier)}
                  onCheckedChange={() => toggle(tool.tool_identifier)}
                />
                <span className="min-w-0 flex-1">
                  <span className="font-mono font-medium break-all">
                    {tool.tool_identifier}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {tool.server_code} ·{" "}
                    {tool.resource_kind
                      ? `调用时解析 ${tool.resource_kind} Resource`
                      : "不需要外部 Resource"}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                    {tool.description.trim() || "暂无工具说明。"}
                  </span>
                  {requiredFileTools.has(tool.tool_identifier) ? (
                    <span className="mt-1 block text-xs text-primary">
                      当前任务文件功能必选
                    </span>
                  ) : null}
                </span>
              </label>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
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
          ["MCP 工具", String(revision?.mcp_tools.length ?? 0)],
          [
            "工作区周期",
            revision?.task_workspace_retention_period ?? "WEEK（兼容默认）",
          ],
          [
            "任务文件能力",
            formatTaskFileFeatures(revision?.task_file_features),
          ],
          ["直接文本文件规则", "TXT/Markdown 可读写，LOG 只读"],
          [
            "文档解析/OCR",
            formatDocumentProcessingSelection(
              revision?.document_processing_profile_code
            ),
          ],
        ]}
      />
    </div>
  )
}

function PublicationTab({ application }: { application: BusinessApplication }) {
  const activate = useActivatePublication(application.code)
  const deactivate = useDeactivateLocalDeployment(application.code)
  const fileOperations = useFileOperations()
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
                      <PublicationMetadata
                        label="工作区周期"
                        value={`${publication.task_workspace_retention_period} · 发布快照`}
                      />
                      <PublicationMetadata
                        label="任务文件能力"
                        value={`${formatTaskFileFeatures(publication.task_file_features)} · 发布快照`}
                      />
                      <PublicationMetadata
                        label="直接文本文件规则"
                        value="平台固定 · TXT/Markdown 可读写，LOG 只读"
                      />
                      <PublicationMetadata
                        label="文档解析/OCR Profile"
                        value={`${publication.document_processing_profile_code} · v${publication.document_processing_profile_version}`}
                      />
                      <PublicationMetadata
                        label="文档解析/OCR 运行状态"
                        value={formatDocumentProcessingRuntimeStatus(
                          publication.document_processing_profile_code,
                          deployment?.active === true &&
                            deployment.publication_id === publication.id,
                          fileOperations.data,
                          fileOperations.isLoading,
                          fileOperations.isError
                        )}
                      />
                      <PublicationMetadata
                        label="Profile 哈希"
                        value={
                          publication.document_processing_profile_hash
                            ? `${publication.document_processing_profile_hash.slice(0, 16)}…`
                            : "无（NONE）"
                        }
                        monospace
                      />
                    </dl>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full sm:w-auto"
                    disabled={
                      application.status !== "enabled" ||
                      activate.isPending
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
  htmlFor?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      {htmlFor ? (
        <Label htmlFor={htmlFor}>{label}</Label>
      ) : (
        <div className="text-sm leading-none font-medium">{label}</div>
      )}
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
  const taskFileFeatures = draft?.task_file_features ?? {
    workspace_enabled: false,
    file_mcp_enabled: false,
    runtime_file_edit_enabled: false,
    default_file_delivery_enabled: false,
  }
  return {
    expected_revision: application.revision,
    agent_publication_id: draft?.agent_publication_id ?? "",
    workflow_publication_id: draft?.workflow_publication_id ?? "",
    task_workspace_retention_period:
      draft?.task_workspace_retention_period ?? "WEEK",
    document_processing_profile_code:
      draft?.document_processing_profile_code ?? "NONE",
    task_file_features: taskFileFeatures,
    session_policy: {
      conversation_mode: "channel",
      recent_message_limit: Number(
        draft?.session_policy.recent_message_limit ?? 20
      ),
      retention_days: Number(draft?.session_policy.retention_days ?? 30),
      continuous_conversation_enabled: Boolean(
        draft?.session_policy.continuous_conversation_enabled ?? false
      ),
      attachments_enabled:
        taskFileFeatures.workspace_enabled ||
        Boolean(draft?.session_policy.attachments_enabled ?? false),
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
    mcp_tools: draft?.mcp_tools.map((tool) => tool.tool_identifier) ?? [],
  }
}

function nextTaskFileFeatures(
  current: SaveDraftInput["task_file_features"],
  key: keyof SaveDraftInput["task_file_features"],
  enabled: boolean
): SaveDraftInput["task_file_features"] {
  const next = { ...current, [key]: enabled }
  if (enabled) {
    if (key === "file_mcp_enabled") next.workspace_enabled = true
    if (key === "runtime_file_edit_enabled") {
      next.workspace_enabled = true
      next.file_mcp_enabled = true
    }
    if (key === "default_file_delivery_enabled") {
      next.workspace_enabled = true
      next.file_mcp_enabled = true
      next.runtime_file_edit_enabled = true
    }
  } else {
    if (key === "workspace_enabled") {
      next.file_mcp_enabled = false
      next.runtime_file_edit_enabled = false
      next.default_file_delivery_enabled = false
    }
    if (key === "file_mcp_enabled") {
      next.runtime_file_edit_enabled = false
      next.default_file_delivery_enabled = false
    }
    if (key === "runtime_file_edit_enabled") {
      next.default_file_delivery_enabled = false
    }
  }
  return next
}

function requiredFileMcpToolIds(
  features: SaveDraftInput["task_file_features"]
): Set<string> {
  const required = new Set<string>()
  if (features.file_mcp_enabled) {
    FILE_MCP_READ_TOOL_IDS.forEach((identifier) => required.add(identifier))
  }
  if (features.runtime_file_edit_enabled) {
    FILE_MCP_EDIT_TOOL_IDS.forEach((identifier) => required.add(identifier))
  }
  if (features.default_file_delivery_enabled) {
    FILE_MCP_DELIVERY_TOOL_IDS.forEach((identifier) => required.add(identifier))
  }
  return required
}

function selectRequiredFileMcpTools(
  selected: string[],
  features: SaveDraftInput["task_file_features"],
  available: Set<string>
): string[] {
  const required = [...requiredFileMcpToolIds(features)].filter((identifier) =>
    available.has(identifier)
  )
  return [...new Set([...selected, ...required])]
}

function formatTaskFileFeatures(
  features: SaveDraftInput["task_file_features"] | null | undefined
): string {
  if (!features) return "全部关闭（兼容默认）"
  const labels = [
    [features.workspace_enabled, "工作区"],
    [features.file_mcp_enabled, "File MCP"],
    [features.runtime_file_edit_enabled, "Write/Edit"],
    [features.default_file_delivery_enabled, "默认交付"],
  ] as const
  const enabled = labels.filter(([active]) => active).map(([, label]) => label)
  return enabled.length ? enabled.join("、") : "全部关闭"
}

function formatDocumentProcessingSelection(
  profile:
    | "NONE"
    | "docling-layout-ocr-v2"
    | null
    | undefined
): string {
  if (!profile || profile === "NONE") return "关闭"
  return `${profile}（已选择）`
}

function formatDocumentProcessingRuntimeStatus(
  profile:
    | "NONE"
    | "docling-layout-ocr-v2",
  active: boolean,
  operations: FileOperations | undefined,
  loading: boolean,
  failed: boolean
): string {
  if (profile === "NONE") return "已关闭"
  if (!active) return "未激活（不评估运行依赖）"
  if (loading) return "正在读取实时状态"
  if (failed || !operations) return "状态不可用（未推断为就绪）"
  if (operations.document_processing.ready) return "就绪"
  return `不可用 · ${formatDocumentProcessingReason(
    operations.document_processing.reason_code
  )}`
}

function formatDocumentProcessingReason(reasonCode: string): string {
  const labels: Record<string, string> = {
    file_service_unavailable: "File Service 未就绪",
    file_processing_worker_not_configured: "Processing Worker 未配置",
    file_processing_worker_unavailable: "Processing Worker 未就绪",
    file_processing_worker_heartbeat_stale: "Processing Worker 心跳过期",
    file_processing_queue_unavailable: "处理队列未就绪",
    rabbitmq_unavailable: "RabbitMQ 未就绪",
    docling_unavailable: "Docling 未就绪",
  }
  return labels[reasonCode] ?? "处理依赖未就绪"
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

function applicationRuntimeLabel(runtimeKind?: "python-v1") {
  if (runtimeKind === "python-v1") return "Python Runtime"
  return "Runtime 未标注"
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
