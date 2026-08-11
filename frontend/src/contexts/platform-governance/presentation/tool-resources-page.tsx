import { useMemo, useState, type FormEvent } from "react"
import {
  BlocksIcon,
  DatabaseIcon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  ServerCogIcon,
} from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import {
  useCreateDraftFromRevision,
  useCreateGovernedResource,
  useDeleteGovernedResourceDraft,
  useGovernedResources,
  usePublishGovernedResource,
  useResourceFormOptions,
  useSaveGovernedResourceDraft,
  useSetResourceIdentityStatus,
  useSetResourceRevisionStatus,
  useVerifyGovernedResource,
} from "@/contexts/platform-governance/application/platform-governance-queries"
import type {
  GovernedResource,
  ResourceFormInput,
  ResourceVerification,
  TopologyItem,
} from "@/contexts/platform-governance/domain/platform-governance"
import { ApiError } from "@/shared/api/api-client"
import { ResourcePolicySheet } from "@/contexts/platform-governance/presentation/resource-policy-sheet"

type Provider = ResourceFormInput["provider_type"]
type ResourceKind = ResourceFormInput["resource_kind"]
type ConfirmAction = {
  type:
    | "delete-draft"
    | "disable-revision"
    | "archive-revision"
    | "disable-identity"
    | "restore-identity"
    | "archive-identity"
  resource: GovernedResource
}

const providerLabels: Record<Provider, string> = {
  mysql: "MySQL",
  sqlserver: "SQL Server",
  oracle: "Oracle 11g",
  redis: "Redis",
  loki: "Loki",
}

const defaultConfigs: Record<Provider, Record<string, unknown>> = {
  mysql: {
    host: "",
    port: 3306,
    database: "",
    username: "",
    schema: "",
  },
  sqlserver: {
    host: "",
    port: 1433,
    database: "",
    username: "",
    schema: "",
  },
  oracle: {
    host: "",
    port: 1521,
    service_name: "",
    username: "",
    schema: "",
  },
  redis: {
    host: "",
    port: 6379,
    database: 0,
    username: "",
    tls: { enabled: false, verify_certificate: true },
  },
  loki: {
    base_url: "http://",
    tenant_id: "",
    timeout_seconds: 10,
    max_minutes: 60,
    max_lines: 1000,
    max_response_bytes: 1048576,
  },
}

function emptyForm(): ResourceFormInput {
  return {
    code: "",
    name: "",
    resource_kind: "database",
    scope_type: "base",
    environment_code: "",
    base_code: "",
    workshop_code: "",
    provider_type: "mysql",
    config: { ...defaultConfigs.mysql },
    secret_refs: {},
  }
}

function formForResource(resource: GovernedResource | null) {
  if (!resource) return emptyForm()
  const source = resource.draft ?? resource.published_revision
  if (!source) return emptyForm()
  return {
    code: resource.code,
    name: resource.name,
    resource_kind: resource.resource_kind,
    scope_type: resource.scope_type,
    environment_code: resource.environment_code,
    base_code: resource.base_code,
    workshop_code: resource.workshop_code,
    provider_type: source.provider_type as Provider,
    config: { ...source.config },
    secret_refs: { ...source.secret_refs },
  }
}

export function ToolResourcesPage() {
  const resources = useGovernedResources()
  const create = useCreateGovernedResource()
  const save = useSaveGovernedResourceDraft()
  const verify = useVerifyGovernedResource()
  const publish = usePublishGovernedResource()
  const createDraft = useCreateDraftFromRevision()
  const removeDraft = useDeleteGovernedResourceDraft()
  const setRevisionStatus = useSetResourceRevisionStatus()
  const setIdentityStatus = useSetResourceIdentityStatus()
  const [filters, setFilters] = useState({
    kind: "all",
    scope: "all",
    identity: "all",
    revision: "all",
    activation: "all",
  })
  const [editing, setEditing] = useState<GovernedResource | null | undefined>(
    undefined
  )
  const [confirm, setConfirm] = useState<ConfirmAction | null>(null)
  const [policyResourceId, setPolicyResourceId] = useState<string | null>(null)
  const confirmPending =
    removeDraft.isPending ||
    setRevisionStatus.isPending ||
    setIdentityStatus.isPending
  const confirmError =
    confirm?.type === "delete-draft"
      ? removeDraft.error
      : confirm?.type.endsWith("-identity")
        ? setIdentityStatus.error
        : setRevisionStatus.error
  const policyResource =
    (resources.data ?? []).find(
      (resource) => resource.id === policyResourceId
    ) ?? null
  const filtered = useMemo(
    () =>
      (resources.data ?? []).filter(
        (resource) =>
          (filters.kind === "all" || resource.resource_kind === filters.kind) &&
          (filters.scope === "all" || resource.scope_type === filters.scope) &&
          (filters.identity === "all" ||
            resource.status === filters.identity) &&
          (filters.revision === "all" ||
            (resource.published_revision?.status ?? "NONE") ===
              filters.revision) &&
          (filters.activation === "all" ||
            resource.activation_status === filters.activation)
      ),
    [filters, resources.data]
  )

  function confirmAction() {
    if (!confirm) return
    const resource = confirm.resource
    if (confirm.type === "delete-draft") {
      if (resource.draft) {
        removeDraft.mutate(
          {
            code: resource.code,
            expectedRevision: resource.draft.draft_revision,
          },
          { onSuccess: () => setConfirm(null) }
        )
      }
      return
    }
    if (confirm.type.endsWith("-identity")) {
      const action = confirm.type.replace("-identity", "") as
        "disable" | "restore" | "archive"
      setIdentityStatus.mutate(
        {
          code: resource.code,
          action,
          expectedRevision: resource.revision,
        },
        { onSuccess: () => setConfirm(null) }
      )
      return
    }
    if (!resource.published_revision) return
    setRevisionStatus.mutate(
      {
        code: resource.code,
        revisionId: resource.published_revision.id,
        action: confirm.type === "disable-revision" ? "disable" : "archive",
      },
      { onSuccess: () => setConfirm(null) }
    )
  }

  return (
    <PageFrame>
      <header>
        <div className="flex items-center gap-2 text-xs font-medium text-primary">
          <ServerCogIcon className="size-4" aria-hidden="true" />
          PLATFORM GOVERNANCE
        </div>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">工具资源</h1>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
              管理 DB、Redis 与 Loki 的稳定资源身份。连接内容按 Draft → VERIFIED
              → PUBLISHED 发布；发布版本不可原地修改，运行状态明确区分
              Published、Effective 与 Last Known Good。
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => void resources.refetch()}
              disabled={resources.isFetching}
            >
              <RefreshCwIcon
                className={resources.isFetching ? "animate-spin" : ""}
                aria-hidden="true"
              />
              刷新
            </Button>
            <Button onClick={() => setEditing(null)}>
              <PlusIcon aria-hidden="true" />
              新建资源
            </Button>
          </div>
        </div>
      </header>

      <ResourceFilters value={filters} onChange={setFilters} />

      {resources.isLoading ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      ) : resources.isError ? (
        <MutationError error={resources.error} />
      ) : !filtered.length ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BlocksIcon aria-hidden="true" />
            </EmptyMedia>
            <EmptyTitle>当前筛选下没有工具资源</EmptyTitle>
            <EmptyDescription>
              reset 后从空配置开始，请先在凭据中心创建 Secret，再新建资源
              Draft。
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {filtered.map((resource) => (
            <ResourceCard
              key={resource.id}
              resource={resource}
              verification={
                verify.variables === resource.code
                  ? verify.data
                  : resource.draft_verification
              }
              pending={
                verify.isPending ||
                publish.isPending ||
                createDraft.isPending ||
                removeDraft.isPending ||
                setRevisionStatus.isPending ||
                setIdentityStatus.isPending
              }
              onEdit={() => setEditing(resource)}
              onVerify={() => verify.mutate(resource.code)}
              onPublish={() => publish.mutate(resource.code)}
              onCreateDraft={() => {
                if (!resource.published_revision) return
                createDraft.mutate({
                  code: resource.code,
                  revisionId: resource.published_revision.id,
                })
              }}
              onManagePolicy={() => setPolicyResourceId(resource.id)}
              onConfirm={(type) => {
                removeDraft.reset()
                setRevisionStatus.reset()
                setIdentityStatus.reset()
                setConfirm({ type, resource })
              }}
            />
          ))}
        </div>
      )}

      <MutationError
        error={verify.error ?? publish.error ?? createDraft.error}
      />

      {editing !== undefined ? (
        <ResourceFormSheet
          open
          resource={editing}
          pending={create.isPending || save.isPending}
          error={create.error ?? save.error}
          onOpenChange={(open) => {
            if (!open) setEditing(undefined)
          }}
          onSubmit={(input) => {
            if (editing) {
              if (!editing.draft) return
              save.mutate(
                {
                  code: editing.code,
                  input: {
                    ...input,
                    expected_revision: editing.draft.draft_revision,
                  },
                },
                { onSuccess: () => setEditing(undefined) }
              )
            } else {
              create.mutate(input, {
                onSuccess: () => setEditing(undefined),
              })
            }
          }}
        />
      ) : null}

      {policyResource ? (
        <ResourcePolicySheet
          resource={policyResource}
          resources={resources.data ?? []}
          onOpenChange={(open) => {
            if (!open) setPolicyResourceId(null)
          }}
        />
      ) : null}

      <AlertDialog
        open={Boolean(confirm)}
        onOpenChange={(open) => {
          if (!open) {
            setConfirm(null)
            removeDraft.reset()
            setRevisionStatus.reset()
            setIdentityStatus.reset()
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmTitle(confirm?.type)}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmDescription(confirm?.type)}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <MutationError error={confirmError} />
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              variant={
                confirm?.type === "restore-identity" ? "default" : "destructive"
              }
              onClick={confirmAction}
              disabled={confirmPending}
            >
              {confirmPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : null}
              {confirmPending ? "处理中" : "确认"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageFrame>
  )
}

function ResourceFilters({
  value,
  onChange,
}: {
  value: {
    kind: string
    scope: string
    identity: string
    revision: string
    activation: string
  }
  onChange: (value: {
    kind: string
    scope: string
    identity: string
    revision: string
    activation: string
  }) => void
}) {
  const definitions = [
    {
      label: "资源类型",
      key: "kind",
      items: [
        ["all", "全部"],
        ["database", "数据库"],
        ["redis", "Redis"],
        ["loki", "Loki"],
      ],
    },
    {
      label: "作用域",
      key: "scope",
      items: [
        ["all", "全部"],
        ["global", "全局"],
        ["environment", "环境"],
        ["base", "基地"],
        ["workshop", "车间"],
      ],
    },
    {
      label: "资源身份状态",
      key: "identity",
      items: [
        ["all", "全部"],
        ["enabled", "启用"],
        ["disabled", "停用"],
        ["archived", "归档"],
      ],
    },
    {
      label: "最新发布版本状态",
      key: "revision",
      items: [
        ["all", "全部"],
        ["PUBLISHED", "已发布"],
        ["DISABLED", "已停用"],
        ["ARCHIVED", "已归档"],
        ["NONE", "无发布版本"],
      ],
    },
    {
      label: "生效状态",
      key: "activation",
      items: [
        ["all", "全部"],
        ["EMPTY", "未发布"],
        ["PENDING", "待装载"],
        ["READY", "已生效"],
        ["DEGRADED", "降级"],
        ["BLOCKED", "阻断"],
      ],
    },
  ] as const
  return (
    <Card className="shadow-none">
      <CardContent className="grid gap-3 py-4 sm:grid-cols-2 xl:grid-cols-5">
        {definitions.map((definition) => (
          <Field key={definition.key}>
            <FieldLabel>{definition.label}</FieldLabel>
            <Select
              value={value[definition.key]}
              onValueChange={(next) =>
                onChange({ ...value, [definition.key]: next ?? "all" })
              }
            >
              <SelectTrigger className="w-full" aria-label={definition.label}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {definition.items.map(([key, label]) => (
                  <SelectItem key={key} value={key}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        ))}
      </CardContent>
    </Card>
  )
}

function ResourceCard({
  resource,
  verification,
  pending,
  onEdit,
  onVerify,
  onPublish,
  onCreateDraft,
  onManagePolicy,
  onConfirm,
}: {
  resource: GovernedResource
  verification: ResourceVerification | null | undefined
  pending: boolean
  onEdit: () => void
  onVerify: () => void
  onPublish: () => void
  onCreateDraft: () => void
  onManagePolicy: () => void
  onConfirm: (type: ConfirmAction["type"]) => void
}) {
  const published = resource.published_revision
  const draft = resource.draft
  const identityEnabled = resource.status === "enabled"
  const identityArchiveBlocked =
    Boolean(draft) ||
    published?.status === "PUBLISHED" ||
    resource.affected_applications.some(
      (application) => application.runtime_status !== "NOT_ACTIVE"
    )
  return (
    <Card className="shadow-none">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <DatabaseIcon className="size-4" aria-hidden="true" />
              {resource.name || resource.code}
            </CardTitle>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {resource.code}
            </p>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Badge variant="outline">
              资源身份：{resourceIdentityLabel(resource.status)}
            </Badge>
            <Badge variant={activationVariant(resource.activation_status)}>
              {activationLabel(resource.activation_status)}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid gap-2 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
          <dt className="text-muted-foreground">类型 / Provider</dt>
          <dd>
            {kindLabel(resource.resource_kind)} ·{" "}
            {providerLabels[
              (draft?.provider_type ?? published?.provider_type) as Provider
            ] ?? "未配置"}
          </dd>
          <dt className="text-muted-foreground">范围</dt>
          <dd>{scopeLabel(resource)}</dd>
          <dt className="text-muted-foreground">资源身份状态</dt>
          <dd>
            {resourceIdentityLabel(resource.status)} · r{resource.revision}
          </dd>
          <dt className="text-muted-foreground">Draft</dt>
          <dd>
            {draft
              ? `${draft.status} · d${draft.draft_revision}`
              : "无活动草稿"}
          </dd>
          <dt className="text-muted-foreground">最新发布版本</dt>
          <dd>
            {published
              ? `r${published.revision} · ${published.status}`
              : "尚未发布"}
          </dd>
          <dt className="text-muted-foreground">Effective</dt>
          <dd className="break-all">
            {resource.effective_revision_id || "无生效版本"}
          </dd>
          <dt className="text-muted-foreground">Last Known Good</dt>
          <dd className="break-all">
            {resource.last_known_good_generation_id || "无"}
          </dd>
        </dl>
        {resource.safe_error_summary ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {resource.safe_error_summary}
          </p>
        ) : null}
        {verification ? (
          <p
            role="status"
            className={
              verification.status === "PASSED"
                ? "rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm text-emerald-700"
                : "rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
            }
          >
            技术测试 {verification.status}
            {verification.safe_error_summary
              ? `：${verification.safe_error_summary}`
              : ""}
          </p>
        ) : null}
        {resource.affected_applications.length ? (
          <div>
            <p className="text-xs font-medium text-muted-foreground">
              受影响应用
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {resource.affected_applications.map((application) => (
                <Badge key={application.publication_id} variant="outline">
                  {application.application_name} · {application.runtime_status}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {resource.resource_kind === "loki" ||
          resource.scope_type === "workshop" ? (
            <Button size="sm" variant="secondary" onClick={onManagePolicy}>
              {resource.resource_kind === "loki"
                ? "配置 Loki 查询范围"
                : "配置车间隔离策略"}
            </Button>
          ) : null}
          {draft ? (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={onEdit}
                disabled={pending || !identityEnabled}
              >
                编辑草稿
              </Button>
              <Button
                size="sm"
                onClick={onVerify}
                disabled={pending || !identityEnabled}
              >
                技术测试
              </Button>
              <Button
                size="sm"
                onClick={onPublish}
                disabled={
                  pending || !identityEnabled || draft.status !== "VERIFIED"
                }
              >
                发布
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => onConfirm("delete-draft")}
                disabled={pending}
              >
                删除草稿
              </Button>
            </>
          ) : published && identityEnabled ? (
            <Button
              size="sm"
              variant="outline"
              onClick={onCreateDraft}
              disabled={pending}
            >
              从 r{published.revision} 新建草稿
            </Button>
          ) : null}
          {published?.status === "PUBLISHED" ? (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => onConfirm("disable-revision")}
              disabled={pending}
            >
              停用发布版本
            </Button>
          ) : published?.status === "DISABLED" ? (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => onConfirm("archive-revision")}
              disabled={pending}
            >
              归档发布版本
            </Button>
          ) : null}
          {resource.status === "enabled" ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onConfirm("disable-identity")}
              disabled={pending}
            >
              停用资源身份
            </Button>
          ) : resource.status === "disabled" ? (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => onConfirm("restore-identity")}
                disabled={pending}
              >
                恢复资源身份
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => onConfirm("archive-identity")}
                disabled={pending || identityArchiveBlocked}
                title={
                  identityArchiveBlocked
                    ? "请先删除草稿、停用发布版本并解除活动应用引用"
                    : undefined
                }
              >
                归档资源身份
              </Button>
            </>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

function ResourceFormSheet({
  open,
  resource,
  pending,
  error,
  onOpenChange,
  onSubmit,
}: {
  open: boolean
  resource: GovernedResource | null
  pending: boolean
  error: unknown
  onOpenChange: (open: boolean) => void
  onSubmit: (input: ResourceFormInput) => void
}) {
  const options = useResourceFormOptions()
  const [form, setForm] = useState<ResourceFormInput>(() =>
    formForResource(resource)
  )
  const [oracleAddressType, setOracleAddressType] = useState<
    "service_name" | "sid"
  >(() => {
    const source = resource?.draft ?? resource?.published_revision
    return source && "sid" in source.config ? "sid" : "service_name"
  })

  const bases = (options.bases.data ?? []).filter(
    (item) => item.environment_code === form.environment_code
  )
  const workshops = (options.workshops.data ?? []).filter(
    (item) =>
      item.environment_code === form.environment_code &&
      item.base_code === form.base_code
  )
  const secrets = (options.secrets.data ?? []).filter(
    (secret) => secret.configured
  )
  const normalizedEnvironmentCode = form.environment_code.trim()
  const environmentExists = (options.environments.data ?? []).some(
    (item) => item.code === normalizedEnvironmentCode
  )
  const createsEnvironment =
    !resource &&
    form.scope_type === "environment" &&
    Boolean(normalizedEnvironmentCode) &&
    !environmentExists

  function setProvider(provider: Provider) {
    const kind: ResourceKind =
      provider === "redis" ? "redis" : provider === "loki" ? "loki" : "database"
    setForm({
      ...form,
      provider_type: provider,
      resource_kind: kind,
      scope_type:
        provider === "loki"
          ? "global"
          : form.scope_type === "global"
            ? "base"
            : form.scope_type,
      environment_code: provider === "loki" ? "" : form.environment_code,
      base_code: provider === "loki" ? "" : form.base_code,
      workshop_code: provider === "loki" ? "" : form.workshop_code,
      config: structuredClone(defaultConfigs[provider]),
      secret_refs: {},
    })
    if (provider === "oracle") setOracleAddressType("service_name")
  }

  function setConfig(name: string, value: unknown) {
    setForm({ ...form, config: { ...form.config, [name]: value } })
  }

  function setSecret(name: string, value: string | null) {
    const next = { ...form.secret_refs }
    if (!value || value === "__none") delete next[name]
    else next[name] = value
    setForm({ ...form, secret_refs: next })
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const normalized = {
      ...form,
      environment_code: normalizedEnvironmentCode,
      base_code: form.base_code.trim(),
      workshop_code: form.workshop_code.trim(),
      config: { ...form.config },
    }
    if (createsEnvironment) normalized.create_environment_if_missing = true
    else delete normalized.create_environment_if_missing
    if (normalized.provider_type === "oracle") {
      if (oracleAddressType === "sid") {
        delete normalized.config.service_name
      } else {
        delete normalized.config.sid
      }
    }
    onSubmit(normalized)
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>
            {resource ? "编辑资源 Draft" : "新建工具资源"}
          </SheetTitle>
          <SheetDescription>
            连接密码只能从凭据中心选择；保存资源时不会提交 Secret 明文。
          </SheetDescription>
        </SheetHeader>
        <form id="resource-form" onSubmit={submit} className="space-y-5 px-4">
          <FieldGroup className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="resource-code">资源编码</FieldLabel>
              <Input
                id="resource-code"
                required
                disabled={Boolean(resource)}
                pattern="[a-z][a-z0-9_-]+"
                value={form.code}
                onChange={(event) =>
                  setForm({ ...form, code: event.target.value })
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="resource-name">资源名称</FieldLabel>
              <Input
                id="resource-name"
                required
                disabled={Boolean(resource)}
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="resource-provider">Provider</FieldLabel>
              <Select
                value={form.provider_type}
                onValueChange={(value) => setProvider(value as Provider)}
              >
                <SelectTrigger
                  id="resource-provider"
                  aria-label="Provider"
                  className="w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(providerLabels) as Provider[]).map(
                    (provider) => (
                      <SelectItem key={provider} value={provider}>
                        {providerLabels[provider]}
                      </SelectItem>
                    )
                  )}
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="resource-scope-type">作用域层级</FieldLabel>
              <Select
                value={form.scope_type}
                disabled={Boolean(resource)}
                onValueChange={(value) =>
                  setForm({
                    ...form,
                    scope_type: value as ResourceFormInput["scope_type"],
                    environment_code:
                      value === "global" ? "" : form.environment_code,
                    base_code:
                      value === "environment" || value === "global"
                        ? ""
                        : form.base_code,
                    workshop_code:
                      value === "workshop" ? form.workshop_code : "",
                  })
                }
              >
                <SelectTrigger
                  id="resource-scope-type"
                  aria-label="作用域层级"
                  className="w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {form.provider_type === "loki" ? (
                    <>
                      <SelectItem value="global">全局</SelectItem>
                      <SelectItem value="environment">环境</SelectItem>
                    </>
                  ) : (
                    <>
                      <SelectItem value="environment">环境</SelectItem>
                      <SelectItem value="base">基地</SelectItem>
                      <SelectItem value="workshop">车间</SelectItem>
                    </>
                  )}
                </SelectContent>
              </Select>
            </Field>
            {form.scope_type !== "global" ? (
              <TopologyCombobox
                label="环境"
                value={form.environment_code}
                disabled={Boolean(resource)}
                options={options.environments.data ?? []}
                allowCustomValue={!resource}
                customValueExists={environmentExists}
                customValueScopeSupported={form.scope_type === "environment"}
                onChange={(environmentCode) =>
                  setForm({
                    ...form,
                    environment_code: environmentCode,
                    base_code: "",
                    workshop_code: "",
                  })
                }
              />
            ) : null}
            {form.scope_type === "base" || form.scope_type === "workshop" ? (
              <TopologyCombobox
                label="基地"
                value={form.base_code}
                disabled={Boolean(resource)}
                options={bases}
                onChange={(baseCode) =>
                  setForm({
                    ...form,
                    base_code: baseCode,
                    workshop_code: "",
                  })
                }
              />
            ) : null}
            {form.scope_type === "workshop" ? (
              <TopologyCombobox
                label="车间"
                value={form.workshop_code}
                disabled={Boolean(resource)}
                options={workshops}
                onChange={(workshopCode) =>
                  setForm({ ...form, workshop_code: workshopCode })
                }
              />
            ) : null}
          </FieldGroup>

          <ProviderFields
            provider={form.provider_type}
            config={form.config}
            secrets={secrets.map((secret) => ({
              code: secret.code,
              ref: secret.secret_ref,
            }))}
            secretRefs={form.secret_refs}
            oracleAddressType={oracleAddressType}
            onOracleAddressType={(value) => {
              setOracleAddressType(value)
              const next = { ...form.config }
              if (value === "sid") {
                delete next.service_name
                next.sid = ""
              } else {
                delete next.sid
                next.service_name = ""
              }
              setForm({ ...form, config: next })
            }}
            onConfig={setConfig}
            onSecret={setSecret}
          />
          <MutationError error={error} />
        </form>
        <SheetFooter>
          <Button form="resource-form" type="submit" disabled={pending}>
            {pending ? (
              <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
            ) : null}
            保存 Draft
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function TopologyCombobox({
  label,
  value,
  disabled,
  options,
  allowCustomValue = false,
  customValueExists = true,
  customValueScopeSupported = true,
  onChange,
}: {
  label: string
  value: string
  disabled: boolean
  options: TopologyItem[]
  allowCustomValue?: boolean
  customValueExists?: boolean
  customValueScopeSupported?: boolean
  onChange: (value: string) => void
}) {
  const optionCodes = options.map((option) => option.code)
  const customValue =
    allowCustomValue && Boolean(value.trim()) && !customValueExists
  const inputId = `resource-${label}-code`

  return (
    <Field>
      <FieldLabel htmlFor={inputId}>{label}</FieldLabel>
      {allowCustomValue ? (
        <>
          <Input
            id={inputId}
            required
            disabled={disabled}
            list={`${inputId}-options`}
            pattern="[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}"
            maxLength={128}
            placeholder={`输入或选择${label}`}
            value={value}
            onChange={(event) => onChange(event.target.value)}
          />
          <datalist id={`${inputId}-options`}>
            {options.map((option) => (
              <option
                key={option.id}
                value={option.code}
                label={option.display_name || option.code}
              />
            ))}
          </datalist>
        </>
      ) : (
        <Combobox
          items={optionCodes}
          value={value}
          disabled={disabled}
          onValueChange={(next) => onChange(String(next ?? ""))}
        >
          <ComboboxInput
            id={inputId}
            required
            disabled={disabled}
            aria-label={label}
            placeholder={`选择${label}`}
          />
          <ComboboxContent>
            <ComboboxEmpty>没有可用{label}</ComboboxEmpty>
            <ComboboxList>
              {options.map((option) => (
                <ComboboxItem key={option.id} value={option.code}>
                  <span>{option.display_name || option.code}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {option.code}
                  </span>
                </ComboboxItem>
              ))}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
      )}
      {allowCustomValue ? (
        customValue ? (
          <FieldDescription
            className={
              customValueScopeSupported ? "text-amber-700" : "text-destructive"
            }
          >
            {customValueScopeSupported
              ? `环境“${value.trim()}”尚不存在，保存 Draft 时将同时创建。`
              : "新环境只能用于环境级作用域；基地或车间作用域必须选择已有环境。"}
          </FieldDescription>
        ) : (
          <FieldDescription>
            可选择已有环境，也可直接输入环境编码。
          </FieldDescription>
        )
      ) : null}
    </Field>
  )
}

function ProviderFields({
  provider,
  config,
  secrets,
  secretRefs,
  oracleAddressType,
  onOracleAddressType,
  onConfig,
  onSecret,
}: {
  provider: Provider
  config: Record<string, unknown>
  secrets: Array<{ code: string; ref: string }>
  secretRefs: Record<string, string>
  oracleAddressType: "service_name" | "sid"
  onOracleAddressType: (value: "service_name" | "sid") => void
  onConfig: (name: string, value: unknown) => void
  onSecret: (name: string, value: string | null) => void
}) {
  const input = (
    name: string,
    label: string,
    options: {
      required?: boolean
      numeric?: boolean
      min?: number
      max?: number
    } = {}
  ) => (
    <Field key={name}>
      <FieldLabel htmlFor={`resource-${name}`}>{label}</FieldLabel>
      <Input
        id={`resource-${name}`}
        type={options.numeric ? "number" : "text"}
        required={options.required}
        min={options.min}
        max={options.max}
        value={String(config[name] ?? "")}
        onChange={(event) =>
          onConfig(
            name,
            options.numeric ? Number(event.target.value) : event.target.value
          )
        }
      />
    </Field>
  )
  if (provider === "loki") {
    return (
      <FieldGroup className="grid gap-4 sm:grid-cols-2">
        {input("base_url", "Base URL", { required: true })}
        {input("tenant_id", "Tenant ID")}
        {input("timeout_seconds", "超时（秒）", {
          required: true,
          numeric: true,
          min: 1,
          max: 60,
        })}
        {input("max_minutes", "最大查询分钟", {
          required: true,
          numeric: true,
          min: 1,
          max: 1440,
        })}
        {input("max_lines", "最大行数", {
          required: true,
          numeric: true,
          min: 1,
          max: 5000,
        })}
        {input("max_response_bytes", "最大响应字节", {
          required: true,
          numeric: true,
          min: 1024,
          max: 10485760,
        })}
        <SecretCombobox
          label="认证凭据（可选）"
          value={secretRefs.auth_ref ?? ""}
          secrets={secrets}
          optional
          onChange={(value) => onSecret("auth_ref", value)}
        />
      </FieldGroup>
    )
  }
  if (provider === "redis") {
    const tls =
      typeof config.tls === "object" && config.tls
        ? (config.tls as Record<string, unknown>)
        : {}
    return (
      <FieldGroup className="grid gap-4 sm:grid-cols-2">
        {input("host", "Host", { required: true })}
        {input("port", "Port", {
          required: true,
          numeric: true,
          min: 1,
          max: 65535,
        })}
        {input("database", "Database", {
          required: true,
          numeric: true,
          min: 0,
          max: 15,
        })}
        {input("username", "Username（可选）")}
        <Field>
          <FieldLabel>TLS</FieldLabel>
          <Select
            value={tls.enabled ? "enabled" : "disabled"}
            onValueChange={(value) =>
              onConfig("tls", {
                enabled: value === "enabled",
                verify_certificate: true,
              })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="disabled">关闭</SelectItem>
              <SelectItem value="enabled">启用并校验证书</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <SecretCombobox
          label="密码凭据（可选）"
          value={secretRefs.password_ref ?? ""}
          secrets={secrets}
          optional
          onChange={(value) => onSecret("password_ref", value)}
        />
      </FieldGroup>
    )
  }
  return (
    <FieldGroup className="grid gap-4 sm:grid-cols-2">
      {input("host", "Host", { required: true })}
      {input("port", "Port", {
        required: true,
        numeric: true,
        min: 1,
        max: 65535,
      })}
      {provider === "oracle" ? (
        <>
          <Field>
            <FieldLabel>Oracle 地址类型</FieldLabel>
            <Select
              value={oracleAddressType}
              onValueChange={(value) =>
                onOracleAddressType(value as "service_name" | "sid")
              }
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="service_name">Service Name</SelectItem>
                <SelectItem value="sid">SID</SelectItem>
              </SelectContent>
            </Select>
            <FieldDescription>
              单实例结构化配置，Service Name 与 SID 二选一。
            </FieldDescription>
          </Field>
          {input(
            oracleAddressType,
            oracleAddressType === "sid" ? "SID" : "Service Name",
            { required: true }
          )}
        </>
      ) : (
        input("database", "Database", { required: true })
      )}
      {input("username", "Username", { required: true })}
      {input("schema", "Schema（可选）")}
      <SecretCombobox
        label="密码凭据"
        value={secretRefs.password_ref ?? ""}
        secrets={secrets}
        onChange={(value) => onSecret("password_ref", value)}
      />
    </FieldGroup>
  )
}

function SecretCombobox({
  label,
  value,
  secrets,
  optional = false,
  onChange,
}: {
  label: string
  value: string
  secrets: Array<{ code: string; ref: string }>
  optional?: boolean
  onChange: (value: string | null) => void
}) {
  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <Combobox
        items={[
          ...(optional ? ["__none"] : []),
          ...secrets.map((secret) => secret.ref),
        ]}
        value={value || (optional ? "__none" : "")}
        onValueChange={(next) => onChange(String(next ?? ""))}
      >
        <ComboboxInput
          required={!optional}
          placeholder="从凭据中心选择"
          aria-label={label}
        />
        <ComboboxContent>
          <ComboboxEmpty>没有可用平台 Secret</ComboboxEmpty>
          <ComboboxList>
            {optional ? (
              <ComboboxItem value="__none">不使用凭据</ComboboxItem>
            ) : null}
            {secrets.map((secret) => (
              <ComboboxItem key={secret.ref} value={secret.ref}>
                <span>{secret.code}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {secret.ref}
                </span>
              </ComboboxItem>
            ))}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
      <FieldDescription>
        仅保存 secret://platform/... 引用，不保存明文。
      </FieldDescription>
    </Field>
  )
}

function kindLabel(kind: GovernedResource["resource_kind"]) {
  return { database: "数据库", redis: "Redis", loki: "Loki" }[kind]
}

function scopeLabel(resource: GovernedResource) {
  if (resource.scope_type === "global") return "global"
  return [resource.environment_code, resource.base_code, resource.workshop_code]
    .filter(Boolean)
    .join(" / ")
}

function resourceIdentityLabel(status: GovernedResource["status"]) {
  return { enabled: "启用", disabled: "停用", archived: "归档" }[status]
}

function activationLabel(status: string) {
  return (
    {
      EMPTY: "未发布",
      PENDING: "待装载",
      READY: "已生效",
      ACTIVE: "已生效",
      DEGRADED: "降级",
      BLOCKED: "阻断",
    }[status] ?? status
  )
}

function activationVariant(
  status: string
): "default" | "secondary" | "outline" | "destructive" {
  if (status === "READY" || status === "ACTIVE") return "default"
  if (status === "DEGRADED" || status === "BLOCKED") return "destructive"
  return status === "PENDING" ? "secondary" : "outline"
}

function confirmTitle(type: ConfirmAction["type"] | undefined) {
  if (type === "delete-draft") return "删除当前 Draft？"
  if (type === "disable-revision") return "停用已发布版本？"
  if (type === "archive-revision") return "归档已停用版本？"
  if (type === "disable-identity") return "停用资源身份？"
  if (type === "restore-identity") return "恢复资源身份？"
  return "归档资源身份？"
}

function confirmDescription(type: ConfirmAction["type"] | undefined) {
  if (type === "delete-draft") {
    return "只删除可编辑草稿，不影响已有 Published 与 Effective 版本。"
  }
  if (type === "disable-revision") {
    return "发布版本不会被物理删除；依赖此版本的应用可能被标记为降级或阻断。"
  }
  if (type === "archive-revision") {
    return "归档后该发布版本不可恢复为可用状态，历史与审计仍会保留。"
  }
  if (type === "disable-identity") {
    return "停用后不能创建、编辑、测试或发布新的资源草稿；既有发布版本、应用和 Job 不会被改写。"
  }
  if (type === "restore-identity") {
    return "恢复后可以继续管理新的资源草稿；历史发布版本状态不会改变。"
  }
  return "资源身份归档后不可恢复。系统只允许归档无草稿、无已发布版本且无活动应用引用的已停用身份。"
}

function MutationError({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <FieldError>
      {error instanceof ApiError ? error.message : "操作失败，请刷新后重试。"}
    </FieldError>
  )
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      {children}
    </div>
  )
}
