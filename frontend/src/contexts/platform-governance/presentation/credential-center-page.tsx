import {
  ListPage,
  ListSearch,
  ListEmpty,
  ListResults,
  CatalogPager,
  ExpandableListRow,
  ListStatus,
  RefreshList,
  ListStatusFilter,
} from "@/shared/presentation/list-page"
import {
  useListNavigation,
  catalogPage,
  matchesListSearch,
} from "@/shared/presentation/list-navigation"
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetHeader,
} from "@/components/ui/sheet"
import { useState, type FormEvent } from "react"
import { PlusIcon, LoaderCircleIcon, RotateCwIcon } from "lucide-react"

import {
  AlertDialog,
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
  const list = useListNavigation()
  const q = list.params.get("q") ?? ""
  const status = list.params.get("status") ?? ""
  const filtered = Boolean(q || status)
  const clear = () => list.filter({ q: "", status: "" })
  const result = catalogPage(
    (secrets.data ?? []).filter(
      (item) =>
        matchesListSearch(q, item.code, item.purpose) &&
        (!status || (item.configured ? "enabled" : "disabled") === status)
    ),
    list.page
  )
  const [creating, setCreating] = useState(false)
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
      onSuccess: () => {
        setCreateForm({ code: "", purpose: "", value: "" })
        setCreating(false)
      },
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
    <ListPage
      title="凭据中心"
      actions={
        <>
          <RefreshList
            refresh={() => void secrets.refetch()}
            busy={secrets.isFetching}
          />
          <Button onClick={() => setCreating(true)}>
            <PlusIcon />
            新建凭据
          </Button>
        </>
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <ListSearch
          label="搜索凭据"
          placeholder="搜索凭据编码或用途"
          value={q}
          onCommit={(q) => list.filter({ q })}
        />
        <ListStatusFilter
          value={status}
          onChange={(status) => list.filter({ status })}
        />
        {filtered && (
          <Button variant="ghost" onClick={clear}>
            重置
          </Button>
        )}
      </div>
      <Sheet
        open={creating}
        onOpenChange={(open) => {
          if (create.isPending) return
          setCreating(open)
          if (!open) {
            setCreateForm({ code: "", purpose: "", value: "" })
            create.reset()
          }
        }}
      >
        <SheetContent aria-describedby={undefined} className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>新建凭据</SheetTitle>
          </SheetHeader>
          <div className="px-4 pb-4">
            <form onSubmit={submitCreate}>
              <FieldGroup className="grid gap-4">
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
                      setCreateForm({
                        ...createForm,
                        value: event.target.value,
                      })
                    }
                  />
                  <FieldDescription>
                    仅本次提交，不会在响应中返回。
                  </FieldDescription>
                </Field>
              </FieldGroup>
              <MutationError error={create.error} />
              <Button
                className="mt-4"
                type="submit"
                disabled={create.isPending}
              >
                {create.isPending ? (
                  <LoaderCircleIcon
                    className="animate-spin"
                    aria-hidden="true"
                  />
                ) : null}
                加密保存
              </Button>
            </form>
          </div>
        </SheetContent>
      </Sheet>

      <Sheet
        open={Boolean(rotateCode)}
        onOpenChange={(open) => {
          if (!open && !rotate.isPending) {
            setRotateCode("")
            setRotateValue("")
            rotate.reset()
          }
        }}
      >
        <SheetContent aria-describedby={undefined} className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>轮换 {rotateCode}</SheetTitle>
          </SheetHeader>
          <form onSubmit={submitRotation} className="grid gap-3 px-4">
            <Field>
              <FieldLabel htmlFor="rotate-value">新 Secret 明文</FieldLabel>
              <Input
                id="rotate-value"
                type="password"
                required
                autoComplete="new-password"
                value={rotateValue}
                onChange={(e) => setRotateValue(e.target.value)}
              />
            </Field>
            <MutationError error={rotate.error} />
            <Button type="submit" disabled={rotate.isPending}>
              确认轮换
            </Button>
          </form>
        </SheetContent>
      </Sheet>
      <ListResults>
        <CredentialTable
          loading={secrets.isLoading}
          error={secrets.error}
          secrets={result.rows}
          clear={filtered ? clear : undefined}
          usageCode={usageCode}
          onUsage={setUsageCode}
          onRotate={(code) => {
            rotate.reset()
            setRotateValue("")
            setRotateCode(code)
          }}
          onDisable={(target) => {
            disable.reset()
            setDisableTarget(target)
          }}
        />

        {secrets.data && (
          <CatalogPager result={result} onPage={list.numberedPage} />
        )}
      </ListResults>
      <Sheet
        open={Boolean(usageCode)}
        onOpenChange={(open) => {
          if (!open) setUsageCode("")
        }}
      >
        <SheetContent aria-describedby={undefined} className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>引用关系 · {usageCode}</SheetTitle>
          </SheetHeader>
          <div className="px-4 pb-4">
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
          </div>
        </SheetContent>
      </Sheet>

      <AlertDialog
        open={Boolean(disableTarget)}
        onOpenChange={(open) => {
          if (!open && !disable.isPending) setDisableTarget(null)
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
            <MutationError error={disable.error} />
            <AlertDialogCancel>取消</AlertDialogCancel>
            <Button
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
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ListPage>
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
      knowledge_resource_revision: "知识资源版本",
    }[type] ?? type
  )
}

function CredentialTable({
  clear,
  loading,
  error,
  secrets,
  usageCode,
  onUsage,
  onRotate,
  onDisable,
}: {
  clear?: () => void
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
  if (!secrets.length)
    return (
      <ListEmpty
        title={clear ? "没有符合条件的凭据" : "还没有平台 Secret"}
        clear={clear}
      />
    )
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>凭据</TableHead>
          <TableHead className="hidden sm:table-cell">用途</TableHead>
          <TableHead>版本</TableHead>
          <TableHead>状态</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {secrets.map((secret) => (
          <ExpandableListRow
            key={secret.id}
            name={secret.code}
            columns={4}
            cells={
              <>
                <TableCell className="hidden sm:table-cell">
                  {secret.purpose || "—"}
                </TableCell>
                <TableCell>v{secret.active_version}</TableCell>
                <TableCell>
                  <ListStatus
                    status={secret.configured ? "enabled" : "disabled"}
                  />
                </TableCell>
              </>
            }
          >
            <p className="font-mono text-xs break-all">{secret.secret_ref}</p>
            <p className="mt-1 text-sm sm:hidden">{secret.purpose}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant={usageCode === secret.code ? "secondary" : "outline"}
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
          </ExpandableListRow>
        ))}
      </TableBody>
    </Table>
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
