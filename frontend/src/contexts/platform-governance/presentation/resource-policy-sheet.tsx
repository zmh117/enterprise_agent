import { useState } from "react"
import {
  CircleAlertIcon,
  FlaskConicalIcon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Field,
  FieldDescription,
  FieldError,
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
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import {
  useCopyLokiScopePolicyRevision,
  useCopyWorkshopPartitionPolicyRevision,
  useCreateDraftFromRevision,
  useCreateLokiScopePolicy,
  useCreateWorkshopPartitionPolicy,
  useDiscoverLokiLabelValues,
  useLokiScopePolicies,
  useLokiScopePolicy,
  usePublishGovernedResource,
  usePublishLokiScopePolicy,
  usePublishWorkshopPartitionPolicy,
  useResourceFormOptions,
  useSaveLokiScopePolicyDraft,
  useSaveWorkshopPartitionPolicyDraft,
  useTestLokiResourceDraft,
  useVerifyGovernedResource,
  useVerifyLokiScopePolicy,
  useVerifyWorkshopPartitionPolicy,
  useWorkshopPartitionPolicies,
  useWorkshopPartitionPolicy,
} from "@/contexts/platform-governance/application/platform-governance-queries"
import type {
  GovernedResource,
  LokiCondition,
  LokiScopePolicy,
  LokiScopePolicyIdentity,
  LokiScopeVerification,
  WorkshopPartitionPolicy,
  WorkshopPartitionVerification,
} from "@/contexts/platform-governance/domain/platform-governance"
import { ApiError } from "@/shared/api/api-client"

export function ResourcePolicySheet({
  resource,
  resources,
  onOpenChange,
}: {
  resource: GovernedResource
  resources: GovernedResource[]
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Sheet open onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-3xl">
        <SheetHeader>
          <SheetTitle>
            {resource.resource_kind === "loki"
              ? "Loki 查询范围策略"
              : "车间数据隔离策略"}
          </SheetTitle>
          <SheetDescription>
            {resource.resource_kind === "loki"
              ? "先测试 Loki Resource Draft，再以级联下拉选择精确 label key=value；发布后条件会强制注入查询。"
              : "数据库只允许一个精确表前缀；Redis 允许多个完整 namespace 前缀，不接受通配或正则。"}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-8">
          <ResourcePolicySummary resource={resource} />
          {resource.resource_kind === "loki" ? (
            <LokiPolicyManager resource={resource} />
          ) : resource.scope_type === "workshop" ? (
            <WorkshopPolicyManager resource={resource} resources={resources} />
          ) : (
            <Notice>
              Workshop Partition Policy
              只绑定真实车间。环境或基地级资源的访问范围由 Application Mapping
              决定。
            </Notice>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function ResourcePolicySummary({ resource }: { resource: GovernedResource }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{resource.name || resource.code}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 text-xs sm:grid-cols-2">
        <Labeled label="Resource" value={resource.code} />
        <Labeled
          label="Scope"
          value={
            resource.scope_type === "global"
              ? "global"
              : [
                  resource.environment_code,
                  resource.base_code,
                  resource.workshop_code,
                ]
                  .filter(Boolean)
                  .join(" / ")
          }
        />
        <Labeled
          label="Draft"
          value={
            resource.draft
              ? `${resource.draft.status} · d${resource.draft.draft_revision}`
              : "无"
          }
        />
        <Labeled
          label="Published Revision"
          value={resource.published_revision?.id ?? "无"}
        />
      </CardContent>
    </Card>
  )
}

function WorkshopPolicyManager({
  resource,
  resources,
}: {
  resource: GovernedResource
  resources: GovernedResource[]
}) {
  const policies = useWorkshopPartitionPolicies()
  const identity = policies.data?.find(
    (item) =>
      item.environment_code === resource.environment_code &&
      item.base_code === resource.base_code &&
      item.workshop_code === resource.workshop_code
  )
  const detail = useWorkshopPartitionPolicy(identity?.code ?? "")

  if (policies.isLoading || (identity && detail.isLoading)) {
    return <Skeleton className="h-80 w-full" />
  }
  return (
    <WorkshopPolicyEditor
      key={`${identity?.id ?? "new"}:${detail.data?.draft?.draft_revision ?? "published"}`}
      resource={resource}
      resources={resources}
      policy={detail.data ?? null}
    />
  )
}

function WorkshopPolicyEditor({
  resource,
  resources,
  policy,
}: {
  resource: GovernedResource
  resources: GovernedResource[]
  policy: WorkshopPartitionPolicy | null
}) {
  const source = policy?.draft ?? policy?.revisions[0]
  const [code, setCode] = useState(
    policy?.code ?? `partition-${resource.workshop_code.toLowerCase()}`
  )
  const [databaseEnabled, setDatabaseEnabled] = useState(
    source?.database_rule_enabled ?? resource.resource_kind === "database"
  )
  const [databasePrefix, setDatabasePrefix] = useState(
    source?.database_table_prefix ?? `${resource.workshop_code}_`
  )
  const [redisEnabled, setRedisEnabled] = useState(
    source?.redis_rule_enabled ?? resource.resource_kind === "redis"
  )
  const [redisPrefixesText, setRedisPrefixesText] = useState(
    source?.redis_prefixes.join("\n") ?? ""
  )
  const redisResources = resources.filter(
    (item) =>
      item.resource_kind === "redis" &&
      item.published_revision?.status === "PUBLISHED" &&
      item.environment_code === resource.environment_code &&
      (item.scope_type === "environment" ||
        (item.base_code === resource.base_code &&
          (item.scope_type === "base" ||
            item.workshop_code === resource.workshop_code)))
  )
  const [redisRevisionId, setRedisRevisionId] = useState(
    redisResources[0]?.published_revision?.id ?? ""
  )
  const [verification, setVerification] =
    useState<WorkshopPartitionVerification | null>(null)
  const create = useCreateWorkshopPartitionPolicy()
  const save = useSaveWorkshopPartitionPolicyDraft()
  const verify = useVerifyWorkshopPartitionPolicy()
  const publish = usePublishWorkshopPartitionPolicy()
  const copy = useCopyWorkshopPartitionPolicyRevision()
  const pending =
    create.isPending ||
    save.isPending ||
    verify.isPending ||
    publish.isPending ||
    copy.isPending
  const error =
    create.error ?? save.error ?? verify.error ?? publish.error ?? copy.error
  const redisPrefixes = redisPrefixesText
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)

  function saveDraft() {
    if (!policy) {
      create.mutate(
        {
          code,
          environment_code: resource.environment_code,
          base_code: resource.base_code,
          workshop_code: resource.workshop_code,
          database_rule_enabled: databaseEnabled,
          database_table_prefix: databaseEnabled ? databasePrefix : "",
          redis_rule_enabled: redisEnabled,
          redis_prefixes: redisEnabled ? redisPrefixes : [],
        },
        { onSuccess: () => toast.success("Workshop Policy Draft 已创建") }
      )
      return
    }
    if (!policy.draft) return
    save.mutate(
      {
        code: policy.code,
        expectedDraftRevision: policy.draft.draft_revision,
        databaseRuleEnabled: databaseEnabled,
        databaseTablePrefix: databaseEnabled ? databasePrefix : "",
        redisRuleEnabled: redisEnabled,
        redisPrefixes: redisEnabled ? redisPrefixes : [],
      },
      {
        onSuccess: () => {
          setVerification(null)
          toast.success("Workshop Policy Draft 已保存，旧证据不再使用")
        },
      }
    )
  }

  if (policy && !policy.draft) {
    const revision = policy.revisions[0]
    return (
      <div className="space-y-4">
        <PolicyRevisionSummary policy={policy} />
        <Button
          variant="outline"
          disabled={!revision || pending}
          onClick={() =>
            revision &&
            copy.mutate(
              {
                code: policy.code,
                sourceRevisionId: revision.id,
                expectedPolicyRevision: policy.revision,
              },
              {
                onSuccess: () =>
                  toast.success("已从 Published Revision 复制新 Draft"),
              }
            )
          }
        >
          <RefreshCwIcon />从 r{revision?.revision ?? "—"} 复制新 Draft
        </Button>
        <MutationError error={error} />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <section className="space-y-4 rounded-lg border p-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-medium">Workshop Policy Draft</h3>
          {policy?.draft ? (
            <Badge variant="secondary">
              d{policy.draft.draft_revision} · {policy.draft.status}
            </Badge>
          ) : null}
        </div>
        <Field>
          <FieldLabel htmlFor="partition-policy-code">策略编码</FieldLabel>
          <Input
            id="partition-policy-code"
            disabled={Boolean(policy)}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
        </Field>
        <label className="flex items-center gap-2 text-sm font-medium">
          <Checkbox
            checked={databaseEnabled}
            onCheckedChange={(checked) => setDatabaseEnabled(Boolean(checked))}
          />
          数据库表前缀规则
        </label>
        {databaseEnabled ? (
          <Field>
            <FieldLabel htmlFor="database-table-prefix">
              唯一精确表前缀
            </FieldLabel>
            <Input
              id="database-table-prefix"
              value={databasePrefix ?? ""}
              onChange={(event) => setDatabasePrefix(event.target.value)}
              placeholder="GL001_"
            />
            <FieldDescription>
              SQL 中每个物理表都必须匹配此前缀。
            </FieldDescription>
          </Field>
        ) : null}
        <label className="flex items-center gap-2 text-sm font-medium">
          <Checkbox
            checked={redisEnabled}
            onCheckedChange={(checked) => setRedisEnabled(Boolean(checked))}
          />
          Redis namespace 规则
        </label>
        {redisEnabled ? (
          <>
            <Field>
              <FieldLabel htmlFor="redis-prefixes">
                完整 namespace 前缀（每行一个）
              </FieldLabel>
              <Textarea
                id="redis-prefixes"
                rows={5}
                value={redisPrefixesText}
                onChange={(event) => setRedisPrefixesText(event.target.value)}
                placeholder={`cr999.crmes.CRMES_TEST_GL#${resource.workshop_code}@$`}
              />
              <FieldDescription>
                前缀必须包含车间标签；不接受 *、正则或不完整片段。
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel>验证使用的 Redis Published Revision</FieldLabel>
              <Select
                value={redisRevisionId}
                onValueChange={(value) => setRedisRevisionId(value ?? "")}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择 Redis Revision" />
                </SelectTrigger>
                <SelectContent>
                  {redisResources.map((item) => (
                    <SelectItem
                      key={item.published_revision!.id}
                      value={item.published_revision!.id}
                    >
                      {item.name} · r{item.published_revision!.revision}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={
              pending ||
              (!databaseEnabled && !redisEnabled) ||
              (redisEnabled && (!redisPrefixes.length || !redisRevisionId))
            }
            onClick={saveDraft}
          >
            保存策略 Draft
          </Button>
          {policy?.draft ? (
            <Button
              disabled={pending || (redisEnabled && !redisRevisionId)}
              onClick={() =>
                verify.mutate(
                  {
                    code: policy.code,
                    expectedDraftRevision: policy.draft!.draft_revision,
                    redisResourceRevisionId: redisEnabled
                      ? redisRevisionId
                      : undefined,
                  },
                  {
                    onSuccess: (result) => {
                      setVerification(result)
                      toast.success(`策略验证完成：${result.status}`)
                    },
                  }
                )
              }
            >
              <FlaskConicalIcon />
              验证
            </Button>
          ) : null}
          {policy?.draft && verification?.status === "PASSED" ? (
            <Button
              disabled={pending}
              onClick={() =>
                publish.mutate(
                  {
                    code: policy.code,
                    verificationId: verification.id,
                    expectedPolicyRevision: policy.revision,
                  },
                  {
                    onSuccess: () =>
                      toast.success("Workshop Policy Revision 已发布"),
                  }
                )
              }
            >
              发布策略
            </Button>
          ) : null}
        </div>
      </section>
      <VerificationNotice verification={verification} />
      <MutationError error={error} />
      {policy ? <PolicyRevisionSummary policy={policy} /> : null}
    </div>
  )
}

function LokiPolicyManager({ resource }: { resource: GovernedResource }) {
  const policies = useLokiScopePolicies()
  const eligible = (policies.data ?? []).filter(
    (item) =>
      resource.scope_type === "global" ||
      item.environment_code === resource.environment_code
  )
  const [selection, setSelection] = useState("")
  const selectedCode = selection || eligible[0]?.code || "__new__"
  const detail = useLokiScopePolicy(
    selectedCode === "__new__" ? "" : selectedCode
  )

  if (policies.isLoading || (selectedCode !== "__new__" && detail.isLoading)) {
    return <Skeleton className="h-96 w-full" />
  }
  return (
    <div className="space-y-4">
      <Field>
        <FieldLabel>范围策略</FieldLabel>
        <Select
          value={selectedCode}
          onValueChange={(value) => setSelection(value ?? "__new__")}
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {eligible.map((item) => (
              <SelectItem key={item.code} value={item.code}>
                {item.code} · {item.environment_code}
                {item.base_code ? ` / ${item.base_code}` : ""}
              </SelectItem>
            ))}
            <SelectItem value="__new__">新建 Loki Scope Policy</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <LokiPolicyEditor
        key={`${selectedCode}:${detail.data?.draft?.draft_revision ?? "published"}`}
        resource={resource}
        identity={eligible.find((item) => item.code === selectedCode)}
        policy={detail.data ?? null}
      />
    </div>
  )
}

function LokiPolicyEditor({
  resource,
  identity,
  policy,
}: {
  resource: GovernedResource
  identity?: LokiScopePolicyIdentity
  policy: LokiScopePolicy | null
}) {
  const options = useResourceFormOptions()
  const initial =
    policy?.draft?.conditions ?? policy?.revisions[0]?.conditions ?? []
  const [conditions, setConditions] = useState<LokiCondition[]>(initial)
  const [environmentCode, setEnvironmentCode] = useState(
    identity?.environment_code ||
      (resource.scope_type === "global" ? "" : resource.environment_code)
  )
  const [baseCode, setBaseCode] = useState(identity?.base_code ?? "")
  const [code, setCode] = useState(
    policy?.code || `loki-${resource.code.toLowerCase()}-scope`
  )
  const [session, setSession] = useState<{
    id: string
    labels: string[]
  } | null>(null)
  const [values, setValues] = useState<Record<string, string[]>>({})
  const [verification, setVerification] =
    useState<LokiScopeVerification | null>(null)
  const test = useTestLokiResourceDraft()
  const discover = useDiscoverLokiLabelValues()
  const create = useCreateLokiScopePolicy()
  const save = useSaveLokiScopePolicyDraft()
  const verify = useVerifyLokiScopePolicy()
  const publish = usePublishLokiScopePolicy()
  const copy = useCopyLokiScopePolicyRevision()
  const verifyResource = useVerifyGovernedResource()
  const publishResource = usePublishGovernedResource()
  const copyResourceDraft = useCreateDraftFromRevision()
  const pending =
    test.isPending ||
    discover.isPending ||
    create.isPending ||
    save.isPending ||
    verify.isPending ||
    publish.isPending ||
    copy.isPending ||
    verifyResource.isPending ||
    publishResource.isPending ||
    copyResourceDraft.isPending
  const error =
    test.error ??
    discover.error ??
    create.error ??
    save.error ??
    verify.error ??
    publish.error ??
    copy.error ??
    verifyResource.error ??
    publishResource.error ??
    copyResourceDraft.error
  const bases = (options.bases.data ?? []).filter(
    (item) => item.environment_code === environmentCode
  )
  const revisionId =
    policy?.draft?.resource_revision_id || resource.published_revision?.id || ""

  function selectedConditions(excludeIndex?: number) {
    return Object.fromEntries(
      conditions.flatMap((item, index) =>
        index !== excludeIndex && item.key && item.value
          ? [[item.key, item.value]]
          : []
      )
    )
  }

  function selectLabel(index: number, label: string) {
    const next = conditions.map((item, current) =>
      current === index ? { key: label, value: "" } : item
    )
    setConditions(next)
    if (!session || !label) return
    discover.mutate(
      {
        code: resource.code,
        testSessionId: session.id,
        label,
        selectedConditions: selectedConditions(index),
      },
      {
        onSuccess: (result) =>
          setValues((current) => ({ ...current, [label]: result.values })),
      }
    )
  }

  if (policy && !policy.draft) {
    const revision = policy.revisions[0]
    return (
      <div className="space-y-4">
        <LokiRevisionSummary policy={policy} />
        <Button
          variant="outline"
          disabled={!revision || pending}
          onClick={() =>
            revision &&
            copy.mutate(
              {
                code: policy.code,
                sourceRevisionId: revision.id,
                expectedPolicyRevision: policy.revision,
              },
              {
                onSuccess: () =>
                  toast.success("已从 Published Revision 复制新 Draft"),
              }
            )
          }
        >
          <RefreshCwIcon />从 r{revision?.revision ?? "—"} 复制新 Draft
        </Button>
        <MutationError error={error} />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {!resource.published_revision ? (
        <section className="space-y-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
          <div>
            <h3 className="font-medium">先发布 Loki Resource</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Scope Policy 必须冻结不可变的 Published Resource
              Revision，不能直接绑定可编辑 Draft。
            </p>
          </div>
          {resource.draft?.status === "DRAFT" ? (
            <Button
              variant="outline"
              disabled={pending}
              onClick={() =>
                verifyResource.mutate(resource.code, {
                  onSuccess: (result) => {
                    if (result.status === "PASSED") {
                      toast.success("Loki Resource 技术测试通过，可以发布")
                    } else {
                      toast.error(
                        `Loki Resource 技术测试 ${result.status}：${result.safe_error_summary || "请检查连接配置"}`
                      )
                    }
                  },
                })
              }
            >
              {verifyResource.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <FlaskConicalIcon />
              )}
              技术测试 Loki Resource
            </Button>
          ) : resource.draft?.status === "VERIFIED" ? (
            <Button
              disabled={pending}
              onClick={() =>
                publishResource.mutate(resource.code, {
                  onSuccess: () =>
                    toast.success("Loki Resource Revision 已发布"),
                })
              }
            >
              发布 Loki Resource
            </Button>
          ) : (
            <Notice>
              当前 Resource 没有可发布 Draft，请返回资源列表创建 Draft。
            </Notice>
          )}
          {resource.draft_verification &&
          resource.draft_verification.status !== "PASSED" ? (
            <FieldError>
              技术测试 {resource.draft_verification.status}：
              {resource.draft_verification.safe_error_summary ||
                "请检查连接配置"}
            </FieldError>
          ) : null}
        </section>
      ) : null}

      {!resource.draft ? (
        <section className="space-y-3 rounded-lg border p-4">
          <div>
            <h3 className="font-medium">创建标签发现 Draft</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              级联标签发现只读取 Resource Draft。复制只会创建新的可编辑
              Draft，不会修改已发布 Resource Revision。
            </p>
          </div>
          <Button
            variant="outline"
            disabled={pending || !resource.published_revision}
            onClick={() =>
              resource.published_revision &&
              copyResourceDraft.mutate(
                {
                  code: resource.code,
                  revisionId: resource.published_revision.id,
                },
                {
                  onSuccess: () =>
                    toast.success("已从 Published Resource 复制新 Draft"),
                }
              )
            }
          >
            <RefreshCwIcon />从 Resource r
            {resource.published_revision?.revision ?? "—"} 复制 Draft
          </Button>
        </section>
      ) : (
        <section className="space-y-4 rounded-lg border p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-medium">Loki Draft 标签发现</h3>
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() =>
                test.mutate(resource.code, {
                  onSuccess: (result) => {
                    setSession({
                      id: result.test_session_id,
                      labels: result.labels,
                    })
                    setValues({})
                    toast.success(
                      `连接成功，发现 ${result.label_count} 个 label key`
                    )
                  },
                })
              }
            >
              {test.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <FlaskConicalIcon />
              )}
              测试并发现标签
            </Button>
          </div>
          {session ? (
            <>
              <div className="flex flex-wrap gap-2">
                {session.labels.map((label) => (
                  <Badge key={label} variant="outline">
                    {label}
                  </Badge>
                ))}
              </div>
              <div className="space-y-3">
                {conditions.map((condition, index) => (
                  <div
                    key={index}
                    className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]"
                  >
                    <Select
                      value={condition.key}
                      onValueChange={(value) => selectLabel(index, value ?? "")}
                    >
                      <SelectTrigger
                        aria-label={`标签 key ${index + 1}`}
                        className="w-full"
                      >
                        <SelectValue placeholder="选择 label key" />
                      </SelectTrigger>
                      <SelectContent>
                        {session.labels
                          .filter(
                            (label) =>
                              !conditions.some(
                                (item, current) =>
                                  current !== index && item.key === label
                              )
                          )
                          .map((label) => (
                            <SelectItem key={label} value={label}>
                              {label}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                    <Select
                      value={condition.value}
                      disabled={!condition.key || discover.isPending}
                      onValueChange={(value) =>
                        setConditions((current) =>
                          current.map((item, currentIndex) =>
                            currentIndex === index
                              ? { ...item, value: value ?? "" }
                              : item
                          )
                        )
                      }
                    >
                      <SelectTrigger
                        aria-label={`标签 value ${index + 1}`}
                        className="w-full"
                      >
                        <SelectValue placeholder="选择精确 value" />
                      </SelectTrigger>
                      <SelectContent>
                        {(values[condition.key] ?? []).map((value) => (
                          <SelectItem key={value} value={value}>
                            {value}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`删除条件 ${index + 1}`}
                      onClick={() =>
                        setConditions((current) =>
                          current.filter(
                            (_, currentIndex) => currentIndex !== index
                          )
                        )
                      }
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                ))}
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setConditions((current) => [
                    ...current,
                    { key: "", value: "" },
                  ])
                }
              >
                <PlusIcon />
                添加 key-value
              </Button>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              测试通过后才会开放 label key/value 下拉；测试会话有时限且绑定当前
              Draft 内容。
            </p>
          )}
        </section>
      )}

      <section className="space-y-4 rounded-lg border p-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-medium">Loki Scope Policy Draft</h3>
          {policy?.draft ? (
            <Badge variant="secondary">
              d{policy.draft.draft_revision} · {policy.draft.status}
            </Badge>
          ) : null}
        </div>
        <Field>
          <FieldLabel htmlFor="loki-policy-code">策略编码</FieldLabel>
          <Input
            id="loki-policy-code"
            disabled={Boolean(policy)}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
        </Field>
        {!policy ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel>目标环境</FieldLabel>
              <Select
                value={environmentCode}
                disabled={resource.scope_type === "environment"}
                onValueChange={(value) => {
                  setEnvironmentCode(value ?? "")
                  setBaseCode("")
                }}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择环境" />
                </SelectTrigger>
                <SelectContent>
                  {(options.environments.data ?? []).map((item) => (
                    <SelectItem key={item.code} value={item.code}>
                      {item.display_name || item.code}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel>可选基地</FieldLabel>
              <Select
                value={baseCode || "__environment__"}
                onValueChange={(value) =>
                  setBaseCode(value === "__environment__" ? "" : (value ?? ""))
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__environment__">整个环境</SelectItem>
                  {bases.map((item) => (
                    <SelectItem key={item.code} value={item.code}>
                      {item.display_name || item.code}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </div>
        ) : null}
        <Labeled
          label="冻结 Resource Revision"
          value={revisionId || "尚未发布 Resource"}
        />
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">
            强制 AND 条件
          </div>
          {conditions
            .filter((item) => item.key && item.value)
            .map((item) => (
              <Badge key={item.key} variant="outline">
                {item.key}={item.value}
              </Badge>
            ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={
              pending ||
              !revisionId ||
              !environmentCode ||
              !conditions.length ||
              conditions.some((item) => !item.key || !item.value)
            }
            onClick={() => {
              if (!policy) {
                create.mutate(
                  {
                    code,
                    environment_code: environmentCode,
                    base_code: baseCode,
                    resource_revision_id: revisionId,
                    conditions,
                  },
                  {
                    onSuccess: () =>
                      toast.success("Loki Scope Policy Draft 已创建"),
                  }
                )
              } else if (policy.draft) {
                save.mutate(
                  {
                    code: policy.code,
                    expectedDraftRevision: policy.draft.draft_revision,
                    resourceRevisionId: policy.draft.resource_revision_id,
                    conditions,
                  },
                  {
                    onSuccess: () => {
                      setVerification(null)
                      toast.success("Loki Scope Policy Draft 已保存")
                    },
                  }
                )
              }
            }}
          >
            保存策略 Draft
          </Button>
          {policy?.draft ? (
            <Button
              disabled={pending}
              onClick={() =>
                verify.mutate(
                  {
                    code: policy.code,
                    expectedDraftRevision: policy.draft!.draft_revision,
                  },
                  {
                    onSuccess: (result) => {
                      setVerification(result)
                      toast.success(`策略验证完成：${result.status}`)
                    },
                  }
                )
              }
            >
              <FlaskConicalIcon />
              验证
            </Button>
          ) : null}
          {policy?.draft && verification?.status === "PASSED" ? (
            <Button
              disabled={pending}
              onClick={() =>
                publish.mutate(
                  {
                    code: policy.code,
                    verificationId: verification.id,
                    expectedPolicyRevision: policy.revision,
                  },
                  {
                    onSuccess: () =>
                      toast.success("Loki Scope Policy Revision 已发布"),
                  }
                )
              }
            >
              发布策略
            </Button>
          ) : null}
        </div>
      </section>
      <VerificationNotice verification={verification} />
      <MutationError error={error} />
      {policy ? <LokiRevisionSummary policy={policy} /> : null}
    </div>
  )
}

function PolicyRevisionSummary({
  policy,
}: {
  policy: WorkshopPartitionPolicy
}) {
  if (!policy.revisions.length) return null
  return (
    <section className="space-y-3 rounded-lg border p-4">
      <h3 className="font-medium">不可变 Published Revisions</h3>
      {policy.revisions.map((revision) => (
        <div key={revision.id} className="rounded-md bg-muted/40 p-3 text-xs">
          <div className="flex items-center justify-between">
            <strong>r{revision.revision}</strong>
            <Badge>{revision.status}</Badge>
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <Labeled
              label="DB Prefix"
              value={revision.database_table_prefix || "禁用"}
            />
            <Labeled
              label="Redis Prefix"
              value={revision.redis_prefixes.join("、") || "禁用"}
            />
          </div>
        </div>
      ))}
    </section>
  )
}

function LokiRevisionSummary({ policy }: { policy: LokiScopePolicy }) {
  if (!policy.revisions.length) return null
  return (
    <section className="space-y-3 rounded-lg border p-4">
      <h3 className="font-medium">不可变 Published Revisions</h3>
      {policy.revisions.map((revision) => (
        <div key={revision.id} className="rounded-md bg-muted/40 p-3 text-xs">
          <div className="flex items-center justify-between gap-2">
            <strong>r{revision.revision}</strong>
            <Badge
              variant={
                revision.health_status === "DEGRADED"
                  ? "destructive"
                  : revision.health_status === "EMPTY"
                    ? "secondary"
                    : "default"
              }
            >
              {revision.health_status}
            </Badge>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {revision.conditions.map((item) => (
              <Badge key={item.key} variant="outline">
                {item.key}={item.value}
              </Badge>
            ))}
          </div>
          <code className="mt-2 block break-all text-muted-foreground">
            {revision.resource_revision_id}
          </code>
        </div>
      ))}
    </section>
  )
}

function VerificationNotice({
  verification,
}: {
  verification: WorkshopPartitionVerification | LokiScopeVerification | null
}) {
  if (!verification) return null
  return (
    <div
      role="status"
      className={
        verification.status === "PASSED"
          ? "rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm text-emerald-700"
          : "rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
      }
    >
      <div className="flex items-center gap-2 font-medium">
        {verification.zero_match_warning ? (
          <CircleAlertIcon className="size-4" />
        ) : null}
        验证 {verification.status}
        {verification.zero_match_warning ? " · zero-match warning" : ""}
      </div>
      {verification.safe_error_summary ? (
        <p className="mt-1">{verification.safe_error_summary}</p>
      ) : null}
      {verification.zero_match_warning ? (
        <p className="mt-1 text-xs">
          零匹配不会自动放宽前缀或 selector；允许发布为 EMPTY，并保留健康告警。
        </p>
      ) : null}
    </div>
  )
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
      {children}
    </div>
  )
}

function Labeled({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-medium break-all">{value}</div>
    </div>
  )
}

function MutationError({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <FieldError>
      {error instanceof ApiError ? error.message : "操作失败，请刷新后重试。"}
    </FieldError>
  )
}
