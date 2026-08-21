import { useMemo, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { LoaderCircleIcon, RefreshCwIcon, SaveIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { apiRequest, ApiError } from "@/shared/api/api-client"

type EffectiveLimit = { value: number; source: string; revision: number }
type RuntimeValue = {
  id: string
  key: string
  scope_type: string
  scope_code: string
  service_name: string
  revision: number
  value: unknown
  status: string
}
type Diagnostics = {
  tenant_id: string
  config_revision: number
  active_file_limit: EffectiveLimit
  billable_bytes_limit: EffectiveLimit
  usage: {
    workspace_count: number
    active_file_count: number
    billable_bytes: number
    reserved_file_slots: number
    reserved_billable_bytes: number
  }
  incompatible_publications: Array<{
    application_code: string
    publication_id: string
    publication_revision: number
  }>
}

const ACTIVE_KEY = "FILE_WORKSPACE_ACTIVE_FILE_LIMIT"
const BYTES_KEY = "FILE_WORKSPACE_BILLABLE_BYTES_LIMIT"

async function loadDiagnostics(tenant: string) {
  return (
    await apiRequest<{ diagnostics: Diagnostics }>(
      `/api/platform/runtime-config/file-workspace-diagnostics?tenant=${encodeURIComponent(tenant)}`
    )
  ).diagnostics
}

async function listRuntimeValues() {
  return (
    await apiRequest<{ values: RuntimeValue[] }>(
      "/api/platform/runtime-config/values?include_disabled=true"
    )
  ).values
}

export function RuntimeConfigPage() {
  const client = useQueryClient()
  const [tenantDraft, setTenantDraft] = useState("")
  const [tenant, setTenant] = useState("")
  const [activeLimitDraft, setActiveLimitDraft] = useState({ key: "", value: "" })
  const [capacityGiBDraft, setCapacityGiBDraft] = useState({ key: "", value: "" })
  const [message, setMessage] = useState("")
  const diagnostics = useQuery({
    queryKey: ["runtime-config", "file-workspace", tenant],
    queryFn: () => loadDiagnostics(tenant),
    enabled: Boolean(tenant),
  })
  const values = useQuery({
    queryKey: ["runtime-config", "values"],
    queryFn: listRuntimeValues,
    enabled: Boolean(tenant),
  })
  const tenantValues = useMemo(
    () =>
      (values.data ?? []).filter(
        (item) =>
          item.scope_type === "tenant" &&
          item.scope_code === tenant &&
          item.service_name === "file-service"
      ),
    [tenant, values.data]
  )

  const diagnosticsKey = diagnostics.data
    ? `${tenant}:${diagnostics.data.config_revision}`
    : ""
  const activeLimit =
    activeLimitDraft.key === diagnosticsKey
      ? activeLimitDraft.value
      : String(diagnostics.data?.active_file_limit.value ?? 200)
  const capacityGiB =
    capacityGiBDraft.key === diagnosticsKey
      ? capacityGiBDraft.value
      : String((diagnostics.data?.billable_bytes_limit.value ?? 2 * 1024 ** 3) / 1024 ** 3)

  const save = useMutation({
    mutationFn: async () => {
      const active = Number(activeLimit)
      const bytes = Number(capacityGiB) * 1024 * 1024 * 1024
      if (!Number.isInteger(active) || active < 1 || active > 1000) {
        throw new Error("ACTIVE 文件上限必须是 1–1000 的整数")
      }
      if (!Number.isInteger(bytes) || bytes < 1 || bytes > 10 * 1024 * 1024 * 1024) {
        throw new Error("容量必须在 1 Byte–10 GiB 范围内")
      }
      for (const [key, value] of [
        [ACTIVE_KEY, active],
        [BYTES_KEY, bytes],
      ] as const) {
        const existing = tenantValues.find((item) => item.key === key)
        await apiRequest("/api/platform/runtime-config/values", {
          method: "POST",
          body: {
            key,
            scope_type: "tenant",
            scope_code: tenant,
            service_name: "file-service",
            value,
            status: "enabled",
            ...(existing ? { expected_revision: existing.revision } : {}),
          },
        })
      }
    },
    onSuccess: async () => {
      setMessage("tenant 文件工作区配额已保存。")
      await Promise.all([
        client.invalidateQueries({ queryKey: ["runtime-config", "file-workspace", tenant] }),
        client.invalidateQueries({ queryKey: ["runtime-config", "values"] }),
      ])
    },
  })

  const submitTenant = (event: FormEvent) => {
    event.preventDefault()
    setMessage("")
    setTenant(tenantDraft.trim())
  }
  const error = diagnostics.error ?? values.error ?? save.error
  const errorMessage =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : ""

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Runtime Config</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          选择已受治理的 tenant，查看并修改 File Service 工作区配额。配置不会进入 Application Publication。
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Tenant 范围</CardTitle></CardHeader>
        <CardContent>
          <form className="flex max-w-xl items-end gap-3" onSubmit={submitTenant}>
            <Field className="flex-1">
              <FieldLabel htmlFor="runtime-config-tenant">Tenant ID</FieldLabel>
              <Input
                id="runtime-config-tenant"
                value={tenantDraft}
                onChange={(event) => setTenantDraft(event.target.value)}
                required
                maxLength={128}
              />
              <FieldDescription>后端只接受已验证且启用的 tenant 身份。</FieldDescription>
            </Field>
            <Button type="submit" disabled={!tenantDraft.trim()}>
              <RefreshCwIcon aria-hidden="true" />加载
            </Button>
          </form>
        </CardContent>
      </Card>

      {diagnostics.isLoading || values.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircleIcon className="animate-spin" aria-hidden="true" />加载配置诊断…
        </div>
      ) : null}
      {errorMessage ? <p className="text-sm text-destructive">{errorMessage}</p> : null}
      {message ? <p className="text-sm text-emerald-700">{message}</p> : null}

      {diagnostics.data ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Metric label="ACTIVE 文件" value={diagnostics.data.usage.active_file_count} note={`预留 ${diagnostics.data.usage.reserved_file_slots}`} />
            <Metric label="计费容量" value={formatBytes(diagnostics.data.usage.billable_bytes)} note={`预留 ${formatBytes(diagnostics.data.usage.reserved_billable_bytes)}`} />
            <Metric label="工作区" value={diagnostics.data.usage.workspace_count} note={`配置 revision ${diagnostics.data.config_revision}`} />
            <Metric label="不兼容 Publication" value={diagnostics.data.incompatible_publications.length} note="提升到 20 以上前必须为 0" />
          </div>

          <Card>
            <CardHeader><CardTitle>有效配额</CardTitle></CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-4 md:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="active-file-limit">每工作区 ACTIVE 文件上限</FieldLabel>
                  <Input id="active-file-limit" type="number" min={1} max={1000} value={activeLimit} onChange={(event) => setActiveLimitDraft({ key: diagnosticsKey, value: event.target.value })} />
                  <FieldDescription>{diagnostics.data.active_file_limit.source} · revision {diagnostics.data.active_file_limit.revision} · 代码硬上限 1000</FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="billable-capacity">每工作区计费容量（GiB）</FieldLabel>
                  <Input id="billable-capacity" type="number" min={0.000001} max={10} step="any" value={capacityGiB} onChange={(event) => setCapacityGiBDraft({ key: diagnosticsKey, value: event.target.value })} />
                  <FieldDescription>{diagnostics.data.billable_bytes_limit.source} · revision {diagnostics.data.billable_bytes_limit.revision} · 代码硬上限 10 GiB</FieldDescription>
                </Field>
              </div>
              <Button onClick={() => save.mutate()} disabled={save.isPending}>
                {save.isPending ? <LoaderCircleIcon className="animate-spin" aria-hidden="true" /> : <SaveIcon aria-hidden="true" />}
                保存 tenant 配额
              </Button>
            </CardContent>
          </Card>

          {diagnostics.data.incompatible_publications.length ? (
            <Card>
              <CardHeader><CardTitle>升级前置检查</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {diagnostics.data.incompatible_publications.map((item) => (
                  <div key={item.publication_id} className="flex items-center justify-between rounded-md border p-3 text-sm">
                    <span>{item.application_code} · r{item.publication_revision}</span>
                    <Badge variant="outline">缺少目录搜索 Tool</Badge>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

function Metric({ label, value, note }: { label: string; value: string | number; note: string }) {
  return <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">{label}</p><p className="mt-2 text-2xl font-semibold">{value}</p><p className="mt-1 text-xs text-muted-foreground">{note}</p></CardContent></Card>
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(2)} GiB`
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(2)} MiB`
  return `${value} B`
}
