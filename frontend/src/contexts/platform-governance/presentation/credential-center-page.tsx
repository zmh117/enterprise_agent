import { useState, type FormEvent } from "react"
import {
  KeyRoundIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  RotateCwIcon,
  ShieldAlertIcon,
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
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  useCreatePlatformSecret,
  useDisablePlatformSecret,
  usePlatformSecrets,
  usePlatformSecretUsage,
  useRotatePlatformSecret,
} from "@/contexts/platform-governance/application/platform-governance-queries"
import type { PlatformSecret } from "@/contexts/platform-governance/domain/platform-governance"
import { ApiError } from "@/shared/api/api-client"

export function CredentialCenterPage() {
  const secrets = usePlatformSecrets()
  const create = useCreatePlatformSecret()
  const rotate = useRotatePlatformSecret()
  const disable = useDisablePlatformSecret()
  const [createForm, setCreateForm] = useState({
    code: "",
    purpose: "",
    value: "",
  })
  const [rotateCode, setRotateCode] = useState("")
  const [rotateValue, setRotateValue] = useState("")
  const [usageCode, setUsageCode] = useState("")
  const [disableTarget, setDisableTarget] = useState<PlatformSecret | null>(
    null
  )
  const usage = usePlatformSecretUsage(usageCode)

  function submitCreate(event: FormEvent) {
    event.preventDefault()
    create.mutate(createForm, {
      onSuccess: () => setCreateForm({ code: "", purpose: "", value: "" }),
    })
  }

  function submitRotation(event: FormEvent) {
    event.preventDefault()
    rotate.mutate(
      { code: rotateCode, value: rotateValue },
      {
        onSuccess: () => {
          setRotateCode("")
          setRotateValue("")
        },
      }
    )
  }

  return (
    <PageFrame>
      <header>
        <div className="flex items-center gap-2 text-xs font-medium text-primary">
          <KeyRoundIcon className="size-4" aria-hidden="true" />
          PLATFORM GOVERNANCE
        </div>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">凭据中心</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
              管理平台 Secret 的引用和版本。页面只接收一次明文用于加密保存，
              之后仅展示 secret://platform/... 引用，不提供明文、密文或 Master
              Key 的查看与下载。
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => void secrets.refetch()}
            disabled={secrets.isFetching}
          >
            <RefreshCwIcon
              className={secrets.isFetching ? "animate-spin" : ""}
              aria-hidden="true"
            />
            刷新
          </Button>
        </div>
      </header>

      <Card className="border-dashed shadow-none">
        <CardContent className="flex gap-3 py-4 text-sm">
          <ShieldAlertIcon
            className="mt-0.5 size-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <p className="leading-6 text-muted-foreground">
            固定 Master Key 由部署侧只读文件提供，不属于 Web 配置。Vault、KMS
            仍是未实现的预留 Provider，当前不能创建或发布。
          </p>
        </CardContent>
      </Card>

      <Card className="shadow-none">
        <CardHeader>
          <CardTitle>新建平台 Secret</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submitCreate}>
            <FieldGroup className="grid gap-4 md:grid-cols-3">
              <Field>
                <FieldLabel htmlFor="secret-code">凭据编码</FieldLabel>
                <Input
                  id="secret-code"
                  required
                  pattern="[a-z][a-z0-9_-]+"
                  maxLength={120}
                  autoComplete="off"
                  value={createForm.code}
                  onChange={(event) =>
                    setCreateForm({ ...createForm, code: event.target.value })
                  }
                  placeholder="oracle_reader_password"
                />
                <FieldDescription>
                  保存后形成 secret://platform/&lt;code&gt;。
                </FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="secret-purpose">用途</FieldLabel>
                <Input
                  id="secret-purpose"
                  maxLength={200}
                  value={createForm.purpose}
                  onChange={(event) =>
                    setCreateForm({
                      ...createForm,
                      purpose: event.target.value,
                    })
                  }
                  placeholder="Oracle 只读账号密码"
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="secret-value">Secret 明文</FieldLabel>
                <Input
                  id="secret-value"
                  required
                  type="password"
                  autoComplete="new-password"
                  value={createForm.value}
                  onChange={(event) =>
                    setCreateForm({ ...createForm, value: event.target.value })
                  }
                />
                <FieldDescription>
                  仅本次提交，不会在响应中返回。
                </FieldDescription>
              </Field>
            </FieldGroup>
            <MutationError error={create.error} />
            <Button className="mt-4" type="submit" disabled={create.isPending}>
              {create.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : null}
              加密保存
            </Button>
          </form>
        </CardContent>
      </Card>

      {rotateCode ? (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>轮换 {rotateCode}</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={submitRotation}
              className="flex flex-col gap-3 sm:flex-row"
            >
              <Input
                aria-label="新 Secret 明文"
                type="password"
                required
                autoComplete="new-password"
                value={rotateValue}
                onChange={(event) => setRotateValue(event.target.value)}
              />
              <Button type="submit" disabled={rotate.isPending}>
                {rotate.isPending ? (
                  <LoaderCircleIcon
                    className="animate-spin"
                    aria-hidden="true"
                  />
                ) : null}
                确认轮换
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setRotateCode("")
                  setRotateValue("")
                }}
              >
                取消
              </Button>
            </form>
            <MutationError error={rotate.error} />
          </CardContent>
        </Card>
      ) : null}

      <CredentialTable
        loading={secrets.isLoading}
        error={secrets.error}
        secrets={secrets.data ?? []}
        usageCode={usageCode}
        onUsage={setUsageCode}
        onRotate={setRotateCode}
        onDisable={setDisableTarget}
      />

      {usageCode ? (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>引用关系 · {usageCode}</CardTitle>
          </CardHeader>
          <CardContent>
            {usage.isLoading ? (
              <Skeleton className="h-20 w-full" />
            ) : usage.isError ? (
              <MutationError error={usage.error} />
            ) : (
              <div className="space-y-3 text-sm">
                <p>
                  总引用 {usage.data?.usage_count ?? 0}，活动引用{" "}
                  {usage.data?.active_usage_count ?? 0}
                </p>
                {usage.data?.dependencies.length ? (
                  <ul className="space-y-2">
                    {usage.data.dependencies.map((dependency) => (
                      <li
                        key={`${dependency.dependency_type}-${dependency.id}`}
                        className="space-y-2 rounded-lg border p-3 text-xs"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-mono">
                            {dependencyTypeLabel(dependency.dependency_type)} ·{" "}
                            {dependency.code}
                          </span>
                          <Badge
                            variant={
                              dependency.active ? "secondary" : "outline"
                            }
                          >
                            {dependency.status}
                          </Badge>
                        </div>
                        <p className="font-mono text-muted-foreground">
                          {dependency.field_paths.join(" · ")}
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-muted-foreground">当前没有资源引用。</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      <AlertDialog
        open={Boolean(disableTarget)}
        onOpenChange={(open) => {
          if (!open) setDisableTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>停用此 Secret？</AlertDialogTitle>
            <AlertDialogDescription>
              已发布资源可能进入 DEGRADED 或 BLOCKED。运行时会保留 Last Known
              Good，但新版本不会把停用凭据视为可用。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={disable.isPending}
              onClick={() => {
                if (!disableTarget) return
                disable.mutate(disableTarget.code, {
                  onSuccess: () => setDisableTarget(null),
                })
              }}
            >
              停用
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageFrame>
  )
}

function dependencyTypeLabel(type: string) {
  return (
    {
      resource_binding: "资源绑定",
      runtime_config: "运行配置",
      secret_reference: "Secret 引用",
      connector: "集成 Connector",
      webhook_revision: "Webhook Draft",
      webhook_publication: "Webhook Publication",
      model_connection_revision: "模型连接版本",
    }[type] ?? type
  )
}

function CredentialTable({
  loading,
  error,
  secrets,
  usageCode,
  onUsage,
  onRotate,
  onDisable,
}: {
  loading: boolean
  error: Error | null
  secrets: PlatformSecret[]
  usageCode: string
  onUsage: (code: string) => void
  onRotate: (code: string) => void
  onDisable: (secret: PlatformSecret) => void
}) {
  if (loading) return <Skeleton className="h-48 w-full" />
  if (error) return <MutationError error={error} />
  if (!secrets.length) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <KeyRoundIcon aria-hidden="true" />
          </EmptyMedia>
          <EmptyTitle>还没有平台 Secret</EmptyTitle>
          <EmptyDescription>
            先创建凭据，再在 DB、Redis 或 Loki 表单中选择其引用。
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  return (
    <Card className="shadow-none">
      <CardContent className="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>凭据</TableHead>
              <TableHead>用途</TableHead>
              <TableHead>版本</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {secrets.map((secret) => (
              <TableRow key={secret.id}>
                <TableCell>
                  <p className="font-medium">{secret.code}</p>
                  <p className="font-mono text-xs text-muted-foreground">
                    {secret.secret_ref}
                  </p>
                </TableCell>
                <TableCell>{secret.purpose || "未填写"}</TableCell>
                <TableCell>v{secret.active_version}</TableCell>
                <TableCell>
                  <Badge variant={secret.configured ? "secondary" : "outline"}>
                    {secret.configured ? "可用" : "已停用"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant={
                        usageCode === secret.code ? "secondary" : "outline"
                      }
                      onClick={() => onUsage(secret.code)}
                    >
                      查看引用
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!secret.configured}
                      onClick={() => onRotate(secret.code)}
                    >
                      <RotateCwIcon aria-hidden="true" />
                      轮换
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={!secret.configured}
                      onClick={() => onDisable(secret)}
                    >
                      停用
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function MutationError({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <FieldError className="mt-3">
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
