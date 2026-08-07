import { useMemo, useState } from "react"
import {
  ArchiveIcon,
  BanIcon,
  CheckCircle2Icon,
  CircleAlertIcon,
  FlaskConicalIcon,
  LoaderCircleIcon,
  PackageCheckIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  ShieldCheckIcon,
} from "lucide-react"
import { toast } from "sonner"

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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { FieldError } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useAdminCapabilitySummary } from "@/contexts/auth/application/admin-capability-query"
import {
  useBuiltinTool,
  useBuiltinTools,
  usePublishBuiltinTool,
  useReconcileBuiltinTools,
  useSetBuiltinToolReleaseLifecycle,
  useVerifyBuiltinTool,
} from "@/contexts/platform-governance/application/platform-governance-queries"
import type {
  BuiltinTool,
  BuiltinToolLifecycleStatus,
  BuiltinToolRelease,
  BuiltinToolVerification,
} from "@/contexts/platform-governance/domain/platform-governance"
import { ApiError } from "@/shared/api/api-client"

type ConfirmAction =
  | { kind: "reconcile" }
  | { kind: "verify"; tool: BuiltinTool }
  | {
      kind: "publish"
      tool: BuiltinTool
      evidence: BuiltinToolVerification
    }
  | {
      kind: "lifecycle"
      release: BuiltinToolRelease
      status: BuiltinToolLifecycleStatus
      evidence?: BuiltinToolVerification
    }

const statusLabel: Record<string, string> = {
  NOT_RECONCILED: "未对账",
  INSTALLED: "已安装",
  MISSING: "实现缺失",
  DRIFTED: "实现漂移",
  CALLABLE: "可调用",
  LIFECYCLE_BLOCKED: "生命周期阻断",
  UNPUBLISHED: "未发布",
  ACTIVE: "ACTIVE",
  DEPRECATED: "DEPRECATED",
  DISABLED: "DISABLED",
  ARCHIVED: "ARCHIVED",
  PASSED: "PASSED",
  FAILED: "FAILED",
  BLOCKED: "BLOCKED",
}

function statusVariant(status: string) {
  if (["CALLABLE", "INSTALLED", "ACTIVE", "PASSED"].includes(status)) {
    return "default" as const
  }
  if (["MISSING", "DRIFTED", "DISABLED", "FAILED"].includes(status)) {
    return "destructive" as const
  }
  return "secondary" as const
}

function digest(value: string) {
  return value ? `${value.slice(0, 12)}…` : "—"
}

function dateTime(value: string | null | undefined) {
  if (!value) return "—"
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN")
}

function latestCurrentEvidence(tool: BuiltinTool) {
  return [...tool.verifications]
    .filter(
      (item) =>
        item.status === "PASSED" &&
        item.handler_version === tool.manifest.handler_version &&
        item.implementation_digest === tool.code_implementation_digest
    )
    .sort((left, right) => right.verified_at.localeCompare(left.verified_at))[0]
}

function dependencyTotal(release: BuiltinToolRelease) {
  return (
    release.dependencies.active_agent_publications +
    release.dependencies.active_application_publications +
    release.dependencies.recoverable_jobs
  )
}

export function BuiltinToolsPage() {
  const catalog = useBuiltinTools()
  const [selected, setSelected] = useState("")
  const selectedIdentifier =
    selected || catalog.data?.[0]?.manifest.tool_identifier || ""
  const detail = useBuiltinTool(selectedIdentifier)
  const capabilities = useAdminCapabilitySummary()
  const capabilitySet = useMemo(
    () => new Set(capabilities.data?.capabilities ?? []),
    [capabilities.data?.capabilities]
  )
  const reconcile = useReconcileBuiltinTools()
  const verify = useVerifyBuiltinTool()
  const publish = usePublishBuiltinTool()
  const lifecycle = useSetBuiltinToolReleaseLifecycle()
  const [confirm, setConfirm] = useState<ConfirmAction | null>(null)
  const [reasonCode, setReasonCode] = useState("ADMIN_UI")

  const pending =
    reconcile.isPending ||
    verify.isPending ||
    publish.isPending ||
    lifecycle.isPending
  const mutationError =
    reconcile.error ?? verify.error ?? publish.error ?? lifecycle.error

  function can(capability: string) {
    return capabilitySet.has(capability)
  }

  function submitConfirmed() {
    if (!confirm) return
    if (confirm.kind === "reconcile") {
      reconcile.mutate(undefined, {
        onSuccess: (summary) => {
          toast.success(
            `对账完成：安装 ${summary.installed}，漂移 ${summary.drifted}，缺失 ${summary.missing}`
          )
          setConfirm(null)
        },
      })
      return
    }
    if (confirm.kind === "verify") {
      verify.mutate(
        {
          toolIdentifier: confirm.tool.manifest.tool_identifier,
          handlerVersion: confirm.tool.manifest.handler_version,
        },
        {
          onSuccess: (evidence) => {
            toast.success(`机器验证完成：${evidence.status}`)
            setConfirm(null)
          },
        }
      )
      return
    }
    if (confirm.kind === "publish") {
      publish.mutate(
        {
          toolIdentifier: confirm.tool.manifest.tool_identifier,
          handlerVersion: confirm.tool.manifest.handler_version,
          verificationId: confirm.evidence.id,
          idempotencyKey: `ui:${confirm.evidence.id}`,
        },
        {
          onSuccess: (release) => {
            toast.success(`Tool Release r${release.release_revision} 已发布`)
            setConfirm(null)
          },
        }
      )
      return
    }
    const normalizedReason = reasonCode.trim()
    if (!normalizedReason) return
    lifecycle.mutate(
      {
        releaseId: confirm.release.id,
        status: confirm.status,
        reasonCode: normalizedReason,
        verificationId: confirm.evidence?.id,
      },
      {
        onSuccess: (release) => {
          toast.success(`Release 已切换为 ${release.status}`)
          setConfirm(null)
          setReasonCode("ADMIN_UI")
        },
      }
    )
  }

  return (
    <PageFrame>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <ShieldCheckIcon aria-hidden="true" />
            </span>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">
                只读工具
              </h1>
              <p className="text-sm text-muted-foreground">
                管理代码内置 Manifest、安装对账、机器证据与不可变 Tool Release。
              </p>
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => void catalog.refetch()}
            disabled={catalog.isFetching}
          >
            <RefreshCwIcon
              className={catalog.isFetching ? "animate-spin" : ""}
            />
            刷新
          </Button>
          <Button
            onClick={() => setConfirm({ kind: "reconcile" })}
            disabled={!can("builtin_tools.reconcile") || pending}
            title={
              can("builtin_tools.reconcile")
                ? "将代码 Registry 与安装投影进行幂等对账"
                : "缺少 builtin_tools.reconcile 权限"
            }
          >
            <RotateCcwIcon />
            安装对账
          </Button>
        </div>
      </div>

      {capabilities.isSuccess &&
      !["reconcile", "verify", "publish", "lifecycle"].some((action) =>
        can(`builtin_tools.${action}`)
      ) ? (
        <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
          当前角色只有目录读取权限；治理按钮保持禁用，不会以页面权限替代细粒度操作权限。
        </div>
      ) : null}

      <MutationError error={mutationError} />

      <div className="grid min-h-[600px] gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="self-start">
          <CardHeader>
            <CardTitle>代码目录</CardTitle>
            <CardDescription>
              {catalog.data
                ? `${catalog.data.length} 个固定只读工具`
                : "正在读取…"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {catalog.isLoading ? (
              Array.from({ length: 5 }, (_, index) => (
                <Skeleton key={index} className="h-20 w-full" />
              ))
            ) : catalog.isError ? (
              <MutationError error={catalog.error} />
            ) : catalog.data?.length ? (
              catalog.data.map((tool) => {
                const manifest = tool.manifest
                const active = manifest.tool_identifier === selectedIdentifier
                return (
                  <button
                    key={manifest.tool_identifier}
                    type="button"
                    aria-pressed={active}
                    className="w-full rounded-lg border px-3 py-3 text-left transition-colors hover:bg-muted/50 aria-pressed:border-primary aria-pressed:bg-primary/5"
                    onClick={() => setSelected(manifest.tool_identifier)}
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span>
                        <span className="block font-medium">
                          {manifest.display_name}
                        </span>
                        <code className="text-xs text-muted-foreground">
                          {manifest.tool_identifier}
                        </code>
                      </span>
                      <StatusBadge status={tool.effective_status} />
                    </span>
                    <span className="mt-2 block text-xs text-muted-foreground">
                      Tool v{manifest.tool_semantic_version} · Handler{" "}
                      {manifest.handler_version}
                    </span>
                  </button>
                )
              })
            ) : (
              <Empty>
                <EmptyHeader>
                  <EmptyTitle>代码目录为空</EmptyTitle>
                  <EmptyDescription>
                    当前构建未注册内置只读工具。
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            )}
          </CardContent>
        </Card>

        {selectedIdentifier ? (
          detail.isLoading ? (
            <Card>
              <CardContent className="space-y-4 pt-2">
                <Skeleton className="h-9 w-72" />
                <Skeleton className="h-80 w-full" />
              </CardContent>
            </Card>
          ) : detail.data ? (
            <ToolDetail
              tool={detail.data}
              pending={pending}
              can={can}
              onConfirm={setConfirm}
            />
          ) : (
            <MutationError error={detail.error} />
          )
        ) : null}
      </div>

      <ConfirmationDialog
        action={confirm}
        pending={pending}
        reasonCode={reasonCode}
        onReasonCodeChange={setReasonCode}
        onCancel={() => {
          setConfirm(null)
          setReasonCode("ADMIN_UI")
        }}
        onConfirm={submitConfirmed}
      />
    </PageFrame>
  )
}

function ToolDetail({
  tool,
  pending,
  can,
  onConfirm,
}: {
  tool: BuiltinTool
  pending: boolean
  can: (capability: string) => boolean
  onConfirm: (action: ConfirmAction) => void
}) {
  const { manifest, installation } = tool
  const evidence = latestCurrentEvidence(tool)
  const currentRelease = tool.releases.find(
    (release) =>
      release.implementation_digest === tool.code_implementation_digest
  )
  const installReady =
    installation?.installation_status === "INSTALLED" &&
    installation.implementation_digest === tool.code_implementation_digest

  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-xl">{manifest.display_name}</CardTitle>
              <StatusBadge status={tool.effective_status} />
              <Badge variant="outline">{manifest.risk_level} RISK</Badge>
            </div>
            <CardDescription className="mt-1 max-w-3xl">
              {manifest.description}
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => onConfirm({ kind: "verify", tool })}
              disabled={
                !can("builtin_tools.verify") || !installReady || pending
              }
              title={
                !can("builtin_tools.verify")
                  ? "缺少 builtin_tools.verify 权限"
                  : !installReady
                    ? "必须先完成安装对账且实现无漂移"
                    : "运行代码中固定的机器 Verifier"
              }
            >
              <FlaskConicalIcon />
              机器验证
            </Button>
            <Button
              onClick={() =>
                evidence && onConfirm({ kind: "publish", tool, evidence })
              }
              disabled={
                !can("builtin_tools.publish") ||
                !installReady ||
                !evidence ||
                Boolean(currentRelease) ||
                pending
              }
              title={
                !can("builtin_tools.publish")
                  ? "缺少 builtin_tools.publish 权限"
                  : currentRelease
                    ? "当前精确实现已经发布"
                    : !evidence
                      ? "需要当前精确实现的 PASSED 机器证据"
                      : "发布不可变 Tool Release"
              }
            >
              <PackageCheckIcon />
              发布 Release
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="manifest">
          <TabsList variant="line" className="mb-4 flex-wrap">
            <TabsTrigger value="manifest">Manifest</TabsTrigger>
            <TabsTrigger value="installation">Installation</TabsTrigger>
            <TabsTrigger value="evidence">
              Evidence ({tool.verifications.length})
            </TabsTrigger>
            <TabsTrigger value="releases">
              Release ({tool.releases.length})
            </TabsTrigger>
          </TabsList>
          <TabsContent value="manifest">
            <ManifestPanel tool={tool} />
          </TabsContent>
          <TabsContent value="installation">
            <InstallationPanel tool={tool} />
          </TabsContent>
          <TabsContent value="evidence">
            <EvidencePanel tool={tool} />
          </TabsContent>
          <TabsContent value="releases">
            <ReleasePanel
              tool={tool}
              evidence={evidence}
              pending={pending}
              canLifecycle={can("builtin_tools.lifecycle")}
              onConfirm={onConfirm}
            />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

function ManifestPanel({ tool }: { tool: BuiltinTool }) {
  const manifest = tool.manifest
  return (
    <div className="space-y-5">
      <KeyValues
        values={[
          ["Identifier", manifest.tool_identifier],
          ["Tool Semantic Version", manifest.tool_semantic_version],
          ["Handler", `${manifest.handler_id}@${manifest.handler_version}`],
          ["Visibility", manifest.visibility],
          ["Implementation Digest", digest(tool.code_implementation_digest)],
          ["Public Schema Hash", digest(manifest.public_schema_hash)],
        ]}
      />
      <Section title="权限与资源槽">
        <div className="flex flex-wrap gap-2">
          {manifest.required_permissions.map((permission) => (
            <Badge key={permission} variant="outline">
              {permission}
            </Badge>
          ))}
        </div>
        {manifest.resource_slots.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Slot</TableHead>
                <TableHead>资源类型</TableHead>
                <TableHead>必需</TableHead>
                <TableHead>允许 Scope</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {manifest.resource_slots.map((slot) => (
                <TableRow key={slot.code}>
                  <TableCell className="font-mono">{slot.code}</TableCell>
                  <TableCell>{slot.resource_kind}</TableCell>
                  <TableCell>{slot.required ? "是" : "否"}</TableCell>
                  <TableCell>{slot.allowed_scope_types.join(" / ")}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-sm text-muted-foreground">
            该工具不绑定治理资源。
          </p>
        )}
      </Section>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Verifier Plan">
          <KeyValues
            values={[
              [
                "Verifier",
                `${manifest.verifier_plan.verifier_id}@${manifest.verifier_plan.verifier_version}`,
              ],
              ["超时上限", `${manifest.verifier_plan.max_duration_ms} ms`],
              ["结果上限", `${manifest.verifier_plan.max_result_bytes} bytes`],
              ["固定检查", manifest.verifier_plan.checks.join("、") || "—"],
            ]}
          />
        </Section>
        <Section title="Safety Boundary">
          <KeyValues
            values={[
              ["只读", manifest.safety_boundary.read_only ? "是" : "否"],
              [
                "允许效果",
                manifest.safety_boundary.allowed_effects.join("、") || "—",
              ],
              [
                "必需 Guard",
                manifest.safety_boundary.required_guards.join("、") || "—",
              ],
            ]}
          />
        </Section>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <JsonPanel title="Input Schema" value={manifest.input_schema} />
        <JsonPanel title="Output Schema" value={manifest.output_schema} />
      </div>
    </div>
  )
}

function InstallationPanel({ tool }: { tool: BuiltinTool }) {
  const installation = tool.installation
  if (!installation) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>尚未对账</EmptyTitle>
          <EmptyDescription>
            使用“安装对账”建立代码 Manifest
            的安装投影；该操作不会自动验证或发布。
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  const exact =
    installation.implementation_digest === tool.code_implementation_digest
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <StatusBadge status={installation.installation_status} />
        {exact ? (
          <span className="flex items-center gap-1 text-sm text-emerald-700">
            <CheckCircle2Icon className="size-4" /> digest 与当前代码一致
          </span>
        ) : (
          <span className="flex items-center gap-1 text-sm text-destructive">
            <CircleAlertIcon className="size-4" /> digest 与当前代码不一致
          </span>
        )}
      </div>
      <KeyValues
        values={[
          ["Handler Version", installation.handler_version],
          ["Frozen Digest", digest(installation.implementation_digest)],
          ["Code Digest", digest(tool.code_implementation_digest)],
          ["首次发现", dateTime(installation.first_seen_at)],
          ["最近对账", dateTime(installation.last_seen_at)],
          ["安全健康摘要", installation.safe_health_summary || "—"],
        ]}
      />
    </div>
  )
}

function EvidencePanel({ tool }: { tool: BuiltinTool }) {
  if (!tool.verifications.length) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>没有机器验证证据</EmptyTitle>
          <EmptyDescription>
            验证只运行 Manifest 声明的固定检查，不接受手工结果。
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  return (
    <div className="space-y-3">
      {tool.verifications.map((evidence) => (
        <div key={evidence.id} className="rounded-lg border p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <StatusBadge status={evidence.status} />
              <code className="text-xs">{evidence.id}</code>
            </div>
            <span className="text-xs text-muted-foreground">
              {dateTime(evidence.verified_at)}
            </span>
          </div>
          <div className="mt-3 grid gap-3 text-xs sm:grid-cols-3">
            <Labeled label="Handler" value={evidence.handler_version} />
            <Labeled
              label="Implementation Digest"
              value={digest(evidence.implementation_digest)}
            />
            <Labeled label="Verifier" value={evidence.verifier_version} />
          </div>
          {evidence.safe_error_summary ? (
            <p className="mt-3 text-sm text-destructive">
              {evidence.safe_error_summary}
            </p>
          ) : null}
          <JsonPanel
            title="有界结果摘要"
            value={evidence.result_summary}
            compact
          />
        </div>
      ))}
    </div>
  )
}

function ReleasePanel({
  tool,
  evidence,
  pending,
  canLifecycle,
  onConfirm,
}: {
  tool: BuiltinTool
  evidence?: BuiltinToolVerification
  pending: boolean
  canLifecycle: boolean
  onConfirm: (action: ConfirmAction) => void
}) {
  if (!tool.releases.length) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>没有 Tool Release</EmptyTitle>
          <EmptyDescription>
            通过当前实现的机器验证后，才能发布不可变 Release。
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  return (
    <div className="space-y-4">
      {tool.releases.map((release) => {
        const actions = lifecycleActions(release)
        return (
          <div key={release.id} className="rounded-lg border p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    Release r{release.release_revision}
                  </span>
                  <StatusBadge status={release.status} />
                  <Badge variant="outline">
                    Tool v{release.tool_semantic_version}
                  </Badge>
                </div>
                <code className="mt-1 block text-xs text-muted-foreground">
                  {release.id}
                </code>
              </div>
              <div className="flex flex-wrap gap-2">
                {actions.map((action) => {
                  const needsEvidence = action.status === "ACTIVE"
                  const archiveBlocked =
                    action.status === "ARCHIVED" && dependencyTotal(release) > 0
                  return (
                    <Button
                      key={action.status}
                      size="sm"
                      variant={action.destructive ? "destructive" : "outline"}
                      disabled={
                        !canLifecycle ||
                        pending ||
                        archiveBlocked ||
                        (needsEvidence && !evidence)
                      }
                      title={
                        !canLifecycle
                          ? "缺少 builtin_tools.lifecycle 权限"
                          : archiveBlocked
                            ? "仍有活动发布或可恢复 Job 引用"
                            : needsEvidence && !evidence
                              ? "恢复需要当前精确实现的 PASSED 证据"
                              : action.label
                      }
                      onClick={() =>
                        onConfirm({
                          kind: "lifecycle",
                          release,
                          status: action.status,
                          evidence: needsEvidence ? evidence : undefined,
                        })
                      }
                    >
                      {action.icon}
                      {action.label}
                    </Button>
                  )
                })}
              </div>
            </div>
            <div className="mt-4 grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
              <Labeled label="Handler" value={release.handler_version} />
              <Labeled
                label="Implementation Digest"
                value={digest(release.implementation_digest)}
              />
              <Labeled label="Verification" value={release.verification_id} />
              <Labeled
                label="发布时间"
                value={dateTime(release.published_at)}
              />
            </div>
            <div className="mt-4 rounded-md bg-muted/40 p-3">
              <div className="mb-2 text-xs font-medium">依赖摘要</div>
              <div className="grid gap-2 text-xs sm:grid-cols-3">
                <Labeled
                  label="Agent Publication"
                  value={String(release.dependencies.active_agent_publications)}
                />
                <Labeled
                  label="Application Publication"
                  value={String(
                    release.dependencies.active_application_publications
                  )}
                />
                <Labeled
                  label="可恢复 Job"
                  value={String(release.dependencies.recoverable_jobs)}
                />
              </div>
            </div>
            <details className="mt-4">
              <summary className="cursor-pointer text-sm font-medium">
                Lifecycle Audit ({release.lifecycle_audit.length})
              </summary>
              <div className="mt-3 space-y-2">
                {release.lifecycle_audit.map((audit) => (
                  <div
                    key={audit.id}
                    className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-xs"
                  >
                    <span>
                      {audit.previous_status ?? "创建"} → {audit.new_status}
                    </span>
                    <Badge variant="outline">{audit.reason_code}</Badge>
                    <span className="text-muted-foreground">
                      {dateTime(audit.occurred_at)}
                    </span>
                    <code className="ml-auto text-muted-foreground">
                      {audit.correlation_id}
                    </code>
                  </div>
                ))}
              </div>
            </details>
          </div>
        )
      })}
    </div>
  )
}

function lifecycleActions(release: BuiltinToolRelease) {
  if (release.status === "ACTIVE") {
    return [
      {
        status: "DEPRECATED" as const,
        label: "弃用",
        destructive: false,
        icon: <CircleAlertIcon />,
      },
      {
        status: "DISABLED" as const,
        label: "停用",
        destructive: true,
        icon: <BanIcon />,
      },
      {
        status: "ARCHIVED" as const,
        label: "归档",
        destructive: true,
        icon: <ArchiveIcon />,
      },
    ]
  }
  if (release.status === "DEPRECATED") {
    return [
      {
        status: "DISABLED" as const,
        label: "停用",
        destructive: true,
        icon: <BanIcon />,
      },
      {
        status: "ARCHIVED" as const,
        label: "归档",
        destructive: true,
        icon: <ArchiveIcon />,
      },
    ]
  }
  if (release.status === "DISABLED") {
    return [
      {
        status: "ACTIVE" as const,
        label: "恢复 ACTIVE",
        destructive: false,
        icon: <RotateCcwIcon />,
      },
      {
        status: "ARCHIVED" as const,
        label: "归档",
        destructive: true,
        icon: <ArchiveIcon />,
      },
    ]
  }
  return []
}

function ConfirmationDialog({
  action,
  pending,
  reasonCode,
  onReasonCodeChange,
  onCancel,
  onConfirm,
}: {
  action: ConfirmAction | null
  pending: boolean
  reasonCode: string
  onReasonCodeChange: (value: string) => void
  onCancel: () => void
  onConfirm: () => void
}) {
  const lifecycleAction = action?.kind === "lifecycle" ? action : null
  const title =
    action?.kind === "reconcile"
      ? "确认执行安装对账？"
      : action?.kind === "verify"
        ? "确认运行固定机器 Verifier？"
        : action?.kind === "publish"
          ? "确认发布不可变 Tool Release？"
          : lifecycleAction
            ? `确认切换为 ${lifecycleAction.status}？`
            : "确认治理操作？"
  const description =
    action?.kind === "reconcile"
      ? "对账只更新 Manifest/Installation 投影，不会自动验证、发布或切换应用。"
      : action?.kind === "verify"
        ? "验证只运行代码 Manifest 中声明的固定有界检查，结果将作为独立证据保存。"
        : action?.kind === "publish"
          ? "Release 会冻结精确版本、digest、Schema 与验证证据；后续代码变化不会修改历史 Release。"
          : lifecycleAction?.status === "ARCHIVED"
            ? "归档是终态且不可恢复；存在活动依赖时后端会拒绝。"
            : lifecycleAction?.status === "DISABLED"
              ? "停用后新 Job 不可再使用该 Release，已有 Job 也会在分发前失败关闭。"
              : lifecycleAction?.status === "DEPRECATED"
                ? "弃用保留既有调用能力，但新配置应迁移到后续 Release。"
                : "恢复要求当前精确实现已安装、无漂移，并绑定最新 PASSED 机器证据。"
  return (
    <AlertDialog
      open={Boolean(action)}
      onOpenChange={(open) => !open && onCancel()}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {lifecycleAction ? (
          <label className="grid gap-2 text-sm">
            <span className="font-medium">原因代码</span>
            <Input
              aria-label="生命周期原因代码"
              value={reasonCode}
              maxLength={80}
              onChange={(event) => onReasonCodeChange(event.target.value)}
            />
            <span className="text-xs text-muted-foreground">
              必填；会进入生命周期审计。
            </span>
          </label>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>取消</AlertDialogCancel>
          <AlertDialogAction
            variant={
              lifecycleAction?.status === "DISABLED" ||
              lifecycleAction?.status === "ARCHIVED"
                ? "destructive"
                : "default"
            }
            disabled={pending || Boolean(lifecycleAction && !reasonCode.trim())}
            onClick={onConfirm}
          >
            {pending ? <LoaderCircleIcon className="animate-spin" /> : null}
            确认执行
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={statusVariant(status)}>
      {statusLabel[status] ?? status}
    </Badge>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-3 rounded-lg border p-4">
      <h3 className="font-medium">{title}</h3>
      {children}
    </section>
  )
}

function KeyValues({ values }: { values: Array<[string, string]> }) {
  return (
    <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {values.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="mt-1 text-sm break-all">{value}</dd>
        </div>
      ))}
    </dl>
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

function JsonPanel({
  title,
  value,
  compact = false,
}: {
  title: string
  value: Record<string, unknown>
  compact?: boolean
}) {
  return (
    <details className={compact ? "mt-3" : "rounded-lg border p-4"}>
      <summary className="cursor-pointer text-sm font-medium">{title}</summary>
      <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-muted/60 p-3 text-xs break-all whitespace-pre-wrap">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
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

function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      {children}
    </div>
  )
}
