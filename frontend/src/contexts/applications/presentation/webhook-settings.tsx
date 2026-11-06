import { useState, type ReactNode } from "react"
import { ApiError } from "@/shared/api/api-client"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  initialWebhookConfig,
  type WebhookDetail,
} from "@/contexts/applications/domain/webhook"
import {
  getWebhook,
  getWebhookCatalog,
  saveWebhookDraft,
  setWebhookEnabled,
  webhookRevisionAction,
} from "@/contexts/applications/infrastructure/webhook-api"
import { managedChannelKeys } from "@/contexts/applications/application/managed-channel-queries"
import { usePlatformSecrets } from "@/contexts/platform-governance/application/platform-governance-queries"
import { MutationError } from "@/contexts/applications/presentation/applications-page"

const inputClass = "w-full rounded-md border bg-background px-3 py-2 text-sm"
const pretty = (value: unknown) => JSON.stringify(value, null, 2)
const validationError = (message: string) =>
  new ApiError({ status: 400, code: "validation_failed", message })
function objectJson(value: string, label: string): Record<string, unknown> {
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    throw validationError(`${label}必须是合法 JSON`)
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
    throw validationError(`${label}必须是 JSON 对象`)
  return parsed as Record<string, unknown>
}
export function WebhookSettings({
  code,
  onClose,
}: {
  code: string | null
  onClose: () => void
}) {
  const query = useQuery({
    queryKey: ["webhook-detail", code],
    queryFn: () => getWebhook(code!),
    enabled: Boolean(code),
    retry: false,
    refetchOnWindowFocus: false,
  })
  return (
    <Sheet
      open={Boolean(code)}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <SheetContent className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-3xl">
        <SheetHeader>
          <SheetTitle>配置 Webhook</SheetTitle>
          <SheetDescription>
            选择凭据和业务角色，发布并启用后即可在 Agent
            入口中绑定。投递目标在应用中配置。
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-8">
          <MutationError error={query.error} />
          {query.isPending && code ? (
            <p role="status">正在加载 Webhook……</p>
          ) : null}
          {code && query.data && !query.isFetching ? (
            <WebhookForm key={code} initial={query.data} />
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}
function WebhookForm({ initial }: { initial: WebhookDetail }) {
  const client = useQueryClient()
  const catalog = useQuery({
    queryKey: ["webhook-catalog"],
    queryFn: getWebhookCatalog,
    retry: false,
  })
  const secrets = usePlatformSecrets()
  const [detail, setDetail] = useState(initial)
  const [config, setConfig] = useState(() =>
    initial.draft?.config.schema_version === 2
      ? initial.draft.config
      : initialWebhookConfig(initial.definition.trigger_type)
  )
  const [baseline, setBaseline] = useState(() => pretty(config))
  const [sample, setSample] = useState(
    initial.definition.trigger_type === "generic"
      ? '{"id":"synthetic-001","message":"合成测试消息"}'
      : '{"status":"firing","groupKey":"synthetic-001","commonAnnotations":{"summary":"合成测试告警"}}'
  )
  const [preview, setPreview] = useState<unknown>(null)
  const [notice, setNotice] = useState("")
  const dirty = baseline !== pretty(config)
  const definition = detail.definition
  const mutation = useMutation({
    mutationFn: async (
      action: "save" | "validate" | "preview" | "publish" | "toggle"
    ) => {
      setNotice("")
      setPreview(null)
      if (action === "save") {
        const result = await saveWebhookDraft(
          definition.code,
          detail.draft?.revision ?? 0,
          config
        )
        return {
          action,
          updated: await getWebhook(definition.code),
          saved: result.revision.config,
        }
      }
      if (action === "toggle") {
        await setWebhookEnabled(definition, definition.status !== "enabled")
      } else {
        if (!detail.draft || dirty) throw validationError("请先保存草稿")
        const result = await webhookRevisionAction(
          definition.code,
          detail.draft.id,
          action,
          action === "preview" ? objectJson(sample, "示例报文") : undefined
        )
        if (action === "preview")
          return { action, preview: result.preview, updated: detail }
      }
      return { action, updated: await getWebhook(definition.code) }
    },
    onSuccess: (result) => {
      setDetail(result.updated)
      client.setQueryData(["webhook-detail", definition.code], result.updated)
      if (result.saved) {
        const saved = result.saved
        setConfig(saved)
        setBaseline(pretty(saved))
      }
      if (result.preview) setPreview(result.preview)
      setNotice(
        {
          save: "草稿已保存，当前运行版本保持不变。",
          validate: result.updated.draft?.validation.valid
            ? "校验通过，可以预览或发布。"
            : "校验未通过，请处理下面的字段错误。",
          preview: "预览完成，未创建业务任务。",
          publish:
            "发布成功；启用后可在 Agent 入口中选择，再由应用绑定触发和投递。",
          toggle: "启停状态已更新。",
        }[result.action]
      )
      void client.invalidateQueries({ queryKey: managedChannelKeys.all })
      void client.invalidateQueries({ queryKey: ["business-applications"] })
    },
  })
  const busy = mutation.isPending
  const savedActionsDisabled =
    busy || dirty || !detail.draft || detail.draft.config.schema_version !== 2
  return (
    <div className="space-y-5">
      <section className="space-y-2 rounded-lg border p-3 text-sm">
        <p className="font-medium">
          {definition.name} · {definition.code}
        </p>
        <p>
          草稿：{detail.draft ? `r${detail.draft.revision}` : "未保存"} ·
          当前发布：
          {detail.current_publication
            ? `r${detail.current_publication.revision}`
            : "未发布"}{" "}
          · {definition.status === "enabled" ? "已启用" : "已停用"}
        </p>
        <p className="break-all">
          接收路径：/webhooks/v1/{definition.public_id}
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-3"
          disabled={
            busy ||
            (definition.status !== "enabled" &&
              (dirty || !detail.current_publication))
          }
          onClick={() => mutation.mutate("toggle")}
        >
          {definition.status === "enabled" ? "停用 Webhook" : "启用 Webhook"}
        </Button>
      </section>
      {detail.draft && detail.draft.config.schema_version !== 2 && (
        <p role="status" className="rounded-md bg-muted p-3 text-sm">
          此 Webhook 使用旧配置，请选择凭据和业务角色后重新保存、发布并启用。
        </p>
      )}
      <MutationError error={catalog.error} />
      <fieldset disabled={busy} className="space-y-4">
        <Field label="Bearer 凭据引用" id="wh-secret">
          <Input
            id="wh-secret"
            list="wh-secret-options"
            value={config.authentication.secret_ref}
            placeholder="secret://platform/独立凭据编码"
            onChange={(event) =>
              setConfig({
                ...config,
                authentication: {
                  type: "bearer_v1",
                  secret_ref: event.target.value,
                },
              })
            }
          />
          <datalist id="wh-secret-options">
            {secrets.data
              ?.filter((item) => item.configured && item.status === "enabled")
              .map((item) => (
                <option key={item.id} value={item.secret_ref}>
                  {item.code}
                </option>
              ))}
          </datalist>
          <p className="text-xs text-muted-foreground">
            使用独立且至少 32 个高熵字符的 Bearer Token。
            <a
              href="/platform/secrets"
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              在凭据中心创建或轮换
            </a>
            ，此处仅填写引用。
          </p>
          <MutationError error={secrets.error} />
        </Field>
        <fieldset className="space-y-3">
          <legend className="font-medium">业务角色</legend>
          <p className="text-sm text-muted-foreground">
            Webhook
            使用所选角色的应用、工具和数据资源权限。选择角色后无需关联人员。
          </p>
          {catalog.data?.roles.map((role) => (
            <label
              key={role.id}
              className="flex items-center gap-2 rounded-md border p-3"
            >
              <input
                type="checkbox"
                checked={config.role_ids.includes(role.id)}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    role_ids: event.target.checked
                      ? [...config.role_ids, role.id]
                      : config.role_ids.filter((id) => id !== role.id),
                  })
                }
              />
              <span>
                {role.name}{" "}
                <span className="text-xs text-muted-foreground">
                  {role.code}
                </span>
              </span>
            </label>
          ))}
          {catalog.data?.roles.length === 0 && (
            <p className="text-sm text-muted-foreground">
              暂无可分配的业务角色，请在角色与授权中创建并授权。
            </p>
          )}
          {config.role_ids
            .filter((id) => !catalog.data?.roles.some((role) => role.id === id))
            .map((id) => (
              <label
                key={id}
                className="flex items-center gap-2 text-sm text-destructive"
              >
                <input
                  type="checkbox"
                  checked
                  onChange={() =>
                    setConfig({
                      ...config,
                      role_ids: config.role_ids.filter((value) => value !== id),
                    })
                  }
                />
                不可用角色 · {id}（取消选择后重新发布）
              </label>
            ))}
        </fieldset>
        <section className="space-y-2 rounded-lg bg-muted p-3 text-sm">
          <p className="font-medium">
            {definition.trigger_type === "generic"
              ? "通用 JSON"
              : "Grafana 标准告警"}
          </p>
          <p>
            {definition.trigger_type === "generic"
              ? '固定接收 {"id":"唯一事件 ID","message":"任务内容"}。'
              : "接收 Grafana Alertmanager 标准报文，仅 firing 告警触发任务。"}
          </p>
          <p className="text-muted-foreground">
            平台统一处理去重、限流和报文大小限制。
          </p>
        </section>
      </fieldset>
      {dirty ? (
        <p role="status" className="text-sm text-amber-700">
          有未保存修改，请先保存草稿。
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={() => mutation.mutate("save")}>
          保存草稿
        </Button>
        <Button
          variant="outline"
          disabled={savedActionsDisabled}
          onClick={() => mutation.mutate("validate")}
        >
          校验草稿
        </Button>
        <Button
          disabled={savedActionsDisabled || !detail.draft?.validation.valid}
          onClick={() => mutation.mutate("publish")}
        >
          发布草稿
        </Button>
      </div>
      {notice ? (
        <p role="status" className="text-sm">
          {notice}
        </p>
      ) : null}
      <MutationError error={mutation.error} />
      {!dirty && detail.draft?.validation.errors?.length ? (
        <ul
          className="space-y-1 text-sm text-destructive"
          aria-label="校验错误"
        >
          {detail.draft.validation.errors.map((error, index) => (
            <li key={`${error.field}-${index}`}>
              {error.field}：{error.message}
            </li>
          ))}
        </ul>
      ) : null}
      <Field label="合成示例报文（JSON）" id="wh-sample">
        <textarea
          id="wh-sample"
          className={inputClass}
          rows={4}
          maxLength={50000}
          value={sample}
          onChange={(event) => setSample(event.target.value)}
        />
      </Field>
      <Button
        variant="outline"
        disabled={savedActionsDisabled}
        onClick={() => mutation.mutate("preview")}
      >
        预览报文
      </Button>
      {preview ? (
        <pre
          aria-label="报文预览"
          className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap"
        >
          {pretty(preview)}
        </pre>
      ) : null}
    </div>
  )
}
function Field({
  label,
  id,
  children,
}: {
  label: string
  id: string
  children: ReactNode
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  )
}
