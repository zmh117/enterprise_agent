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
  type WebhookConfig,
  type WebhookRecipient,
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
            保存草稿后校验、预览并发布，再启用接收。业务执行还需绑定业务应用并授权服务账号。
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
  const [config, setConfig] = useState(
    () =>
      initial.draft?.config ??
      initialWebhookConfig(initial.definition.trigger_type)
  )
  const [variables, setVariables] = useState(() =>
    pretty(config.mapping.variables)
  )
  const [filters, setFilters] = useState(() => pretty(config.mapping.filters))
  const [target, setTarget] = useState(() => pretty(config.delivery.target))
  const [options, setOptions] = useState(() => pretty(config.delivery.options))
  const [baseline, setBaseline] = useState(() =>
    pretty([config, variables, filters, target, options])
  )
  const [sample, setSample] = useState(
    initial.definition.trigger_type === "generic"
      ? '{"id":"synthetic-001","message":"合成测试消息"}'
      : '{"status":"firing","groupKey":"synthetic-001","commonAnnotations":{"summary":"合成测试告警"}}'
  )
  const [preview, setPreview] = useState<unknown>(null)
  const [notice, setNotice] = useState("")
  const dirty =
    baseline !== pretty([config, variables, filters, target, options])
  const definition = detail.definition
  const mutation = useMutation({
    mutationFn: async (
      action: "save" | "validate" | "preview" | "publish" | "toggle"
    ) => {
      setNotice("")
      setPreview(null)
      if (action === "save") {
        const parsedVariables = objectJson(variables, "变量映射")
        if (
          Object.values(parsedVariables).some(
            (value) => typeof value !== "string"
          )
        )
          throw validationError("变量映射的值必须是 JSON Pointer 字符串")
        let parsedFilters: unknown
        try {
          parsedFilters = JSON.parse(filters)
        } catch {
          throw validationError("过滤条件必须是合法 JSON 数组")
        }
        if (!Array.isArray(parsedFilters))
          throw validationError("过滤条件必须是 JSON 数组")
        const next = {
          ...config,
          mapping: {
            ...config.mapping,
            variables: parsedVariables as Record<string, string>,
            filters: parsedFilters,
          },
          delivery: {
            ...config.delivery,
            target:
              config.delivery.type === "dingtalk_recipients"
                ? config.delivery.target
                : objectJson(target, "投递目标"),
            options: objectJson(options, "投递选项"),
          },
        }
        const result = await saveWebhookDraft(
          definition.code,
          detail.draft?.revision ?? 0,
          next
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
        setVariables(pretty(saved.mapping.variables))
        setFilters(pretty(saved.mapping.filters))
        setTarget(pretty(saved.delivery.target))
        setOptions(pretty(saved.delivery.options))
        setBaseline(
          pretty([
            saved,
            pretty(saved.mapping.variables),
            pretty(saved.mapping.filters),
            pretty(saved.delivery.target),
            pretty(saved.delivery.options),
          ])
        )
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
            "发布成功；启用后可接收请求，业务执行仍需应用绑定和服务账号授权。",
          toggle: "启停状态已更新。",
        }[result.action]
      )
      void client.invalidateQueries({ queryKey: managedChannelKeys.all })
      void client.invalidateQueries({ queryKey: ["business-applications"] })
    },
  })
  const busy = mutation.isPending
  const savedActionsDisabled = busy || dirty || !detail.draft
  const mapping = (patch: Partial<WebhookConfig["mapping"]>) =>
    setConfig({ ...config, mapping: { ...config.mapping, ...patch } })
  const destinations =
    catalog.data?.connectors.filter(
      (item) =>
        item.allow_delivery &&
        ![
          "managed_webhook",
          "grafana_alert",
          "debug_api",
          "dingtalk_enterprise_stream",
        ].includes(item.connector_type)
    ) ?? []
  const recipients = (config.delivery.target.recipients ??
    []) as WebhookRecipient[]
  const robots =
    catalog.data?.connectors.filter((item) => item.supports_robot_delivery) ??
    []
  const updateRecipients = (rows: WebhookRecipient[]) =>
    setConfig({
      ...config,
      delivery: {
        type: "dingtalk_recipients",
        connector_id: "",
        target: { recipients: rows },
        options: {},
      },
    })
  const updateRecipient = (index: number, patch: Partial<WebhookRecipient>) =>
    updateRecipients(
      recipients.map((row, i) => (i === index ? { ...row, ...patch } : row))
    )
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
        <p>
          服务账号：
          <a
            className="underline"
            href={`/users/${encodeURIComponent(definition.service_account_id)}`}
            target="_blank"
            rel="noreferrer"
          >
            {definition.service_account_username}
          </a>
          （
          {definition.service_account_status === "enabled"
            ? "已启用"
            : "已停用"}
          ）
        </p>
        <p className="text-muted-foreground">
          先在 Agent 配置中分配“Webhook · {definition.code}”入口并发布
          Agent，再选择该版本。发布后在业务应用中绑定此
          Webhook，为服务账号分配业务角色与范围。
        </p>
        <a
          className="underline"
          href="/agent-profiles"
          target="_blank"
          rel="noreferrer"
        >
          打开 Agent 配置
        </a>
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
        <Field label="Agent 发布版本" id="wh-agent">
          <select
            id="wh-agent"
            className={inputClass}
            value={config.agent.publication_id}
            onChange={(event) => {
              const selected = catalog.data?.agents.find(
                (item) => item.publication_id === event.target.value
              )
              setConfig({
                ...config,
                agent: {
                  code: selected?.code ?? "",
                  publication_id: selected?.publication_id ?? "",
                },
              })
            }}
          >
            <option value="">请选择已发布 Agent</option>
            {catalog.data?.agents.map((item) => (
              <option key={item.publication_id} value={item.publication_id}>
                {item.name} · {item.code} · r{item.revision}
              </option>
            ))}
          </select>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              void catalog.refetch()
              void secrets.refetch()
            }}
          >
            刷新配置目录
          </Button>
        </Field>
        <h3 className="font-medium">消息映射</h3>
        {config.adapter === "generic_json_v1" ? (
          <Field label="事件 ID 路径" id="wh-event">
            <Input
              id="wh-event"
              value={config.mapping.event_id_pointer}
              onChange={(event) =>
                mapping({ event_id_pointer: event.target.value })
              }
            />
          </Field>
        ) : (
          <p className="text-sm text-muted-foreground">
            Grafana 仅处理 firing 告警组，使用 groupKey 或指纹去重。
          </p>
        )}
        <Field label="变量映射（JSON Pointer）" id="wh-variables">
          <textarea
            id="wh-variables"
            className={inputClass}
            rows={4}
            maxLength={30000}
            value={variables}
            onChange={(event) => setVariables(event.target.value)}
          />
        </Field>
        <Field label="消息模板" id="wh-message">
          <textarea
            id="wh-message"
            className={inputClass}
            rows={3}
            maxLength={10000}
            value={config.mapping.message_template}
            onChange={(event) =>
              mapping({ message_template: event.target.value })
            }
          />
        </Field>
        <Field label="过滤条件（JSON 数组）" id="wh-filters">
          <textarea
            id="wh-filters"
            className={inputClass}
            rows={2}
            maxLength={30000}
            value={filters}
            onChange={(event) => setFilters(event.target.value)}
          />
        </Field>
        <h3 className="font-medium">业务路由</h3>
        <p className="text-xs text-muted-foreground">
          提取模式必须填写允许值，使用英文逗号分隔；报文不能扩大授权范围。
        </p>
        {Object.entries({
          project_code: "项目编码",
          environment: "环境",
          base: "基地",
          workshop: "车间",
          service: "服务",
        }).map(([key, label]) => {
          const rule = config.routing[key]
          const update = (patch: Partial<typeof rule>) =>
            setConfig({
              ...config,
              routing: { ...config.routing, [key]: { ...rule, ...patch } },
            })
          return (
            <div key={key} className="grid gap-2 sm:grid-cols-3">
              <Field label={`${label}模式`} id={`wh-${key}-mode`}>
                <select
                  id={`wh-${key}-mode`}
                  className={inputClass}
                  value={rule.mode}
                  onChange={(event) =>
                    update({ mode: event.target.value as "fixed" | "extract" })
                  }
                >
                  <option value="fixed">固定</option>
                  <option value="extract">从报文提取</option>
                </select>
              </Field>
              <Field
                label={`${label}${rule.mode === "fixed" ? "值" : "路径"}`}
                id={`wh-${key}-value`}
              >
                <Input
                  id={`wh-${key}-value`}
                  value={rule.mode === "fixed" ? rule.value : rule.pointer}
                  onChange={(event) =>
                    update(
                      rule.mode === "fixed"
                        ? { value: event.target.value }
                        : { pointer: event.target.value }
                    )
                  }
                />
              </Field>
              {rule.mode === "extract" ? (
                <Field label={`${label}允许值`} id={`wh-${key}-allowed`}>
                  <Input
                    id={`wh-${key}-allowed`}
                    value={rule.allowed_values.join(",")}
                    onChange={(event) =>
                      update({ allowed_values: event.target.value.split(",") })
                    }
                  />
                </Field>
              ) : null}
            </div>
          )
        })}
        <Field label="结果投递" id="wh-delivery">
          <select
            id="wh-delivery"
            className={inputClass}
            value={
              config.delivery.type === "dingtalk_recipients"
                ? "dingtalk_recipients"
                : config.delivery.connector_id
            }
            onChange={(event) => {
              if (event.target.value === "dingtalk_recipients") {
                updateRecipients([
                  {
                    connector_id: robots[0]?.id ?? "",
                    kind: "group",
                    target_id: "",
                    label: "",
                  },
                ])
                setTarget("{}")
                setOptions("{}")
                return
              }
              const selected = destinations.find(
                (item) => item.id === event.target.value
              )
              setConfig({
                ...config,
                delivery: {
                  type: selected?.connector_type ?? "none",
                  connector_id: selected?.id ?? "",
                  target: {},
                  options: {},
                },
              })
              setTarget("{}")
              setOptions("{}")
            }}
          >
            <option value="">不投递结果</option>
            <option value="dingtalk_recipients">
              钉钉机器人（多个接收人）
            </option>
            {destinations.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {item.connector_type}
              </option>
            ))}
          </select>
        </Field>
        {config.delivery.type === "dingtalk_recipients" ? (
          <section className="space-y-3" aria-label="钉钉结果接收人">
            <p className="text-sm text-muted-foreground">
              Agent 执行完成后发送结果，最多 20 个接收人。群填写
              openConversationId，用户填写该机器人企业内的 userId。 请先在 Agent
              配置中分配这些机器人的投递权限并发布；业务应用的投递绑定选择“使用
              Webhook 配置的接收人”，连接器选择本 Webhook 入口。
            </p>
            {robots.length === 0 ? (
              <p role="status">
                没有可用的钉钉应用机器人，请先在渠道页面创建并启用机器人。
              </p>
            ) : null}
            {recipients.map((row, index) => (
              <div key={index} className="space-y-2 rounded-lg border p-3">
                <Field
                  label={`接收人 ${index + 1} 机器人`}
                  id={`wh-recipient-${index}-robot`}
                >
                  <select
                    id={`wh-recipient-${index}-robot`}
                    className={inputClass}
                    value={row.connector_id}
                    onChange={(event) =>
                      updateRecipient(index, {
                        connector_id: event.target.value,
                      })
                    }
                  >
                    <option value="">请选择钉钉机器人</option>
                    {robots.map((robot) => (
                      <option key={robot.id} value={robot.id}>
                        {robot.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label={`接收人 ${index + 1} 类型`}
                  id={`wh-recipient-${index}-kind`}
                >
                  <select
                    id={`wh-recipient-${index}-kind`}
                    className={inputClass}
                    value={row.kind}
                    onChange={(event) =>
                      updateRecipient(index, {
                        kind: event.target.value as "group" | "user",
                        target_id: "",
                      })
                    }
                  >
                    <option value="group">钉钉群</option>
                    <option value="user">钉钉用户</option>
                  </select>
                </Field>
                <Field
                  label={`接收人 ${index + 1} 目标 ID`}
                  id={`wh-recipient-${index}-target`}
                >
                  <Input
                    id={`wh-recipient-${index}-target`}
                    value={row.target_id}
                    maxLength={256}
                    placeholder={
                      row.kind === "group" ? "openConversationId" : "userId"
                    }
                    onChange={(event) =>
                      updateRecipient(index, { target_id: event.target.value })
                    }
                  />
                </Field>
                <Field
                  label={`接收人 ${index + 1} 备注`}
                  id={`wh-recipient-${index}-label`}
                >
                  <Input
                    id={`wh-recipient-${index}-label`}
                    value={row.label}
                    maxLength={80}
                    onChange={(event) =>
                      updateRecipient(index, { label: event.target.value })
                    }
                  />
                </Field>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    updateRecipients(recipients.filter((_, i) => i !== index))
                  }
                >
                  删除接收人 {index + 1}
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              disabled={recipients.length >= 20}
              onClick={() =>
                updateRecipients([
                  ...recipients,
                  {
                    connector_id: robots[0]?.id ?? "",
                    kind: "group",
                    target_id: "",
                    label: "",
                  },
                ])
              }
            >
              添加接收人
            </Button>
          </section>
        ) : null}
        {config.delivery.connector_id ? (
          <>
            <Field label="投递目标（JSON）" id="wh-target">
              <textarea
                id="wh-target"
                className={inputClass}
                rows={3}
                maxLength={10000}
                value={target}
                onChange={(event) => setTarget(event.target.value)}
              />
            </Field>
            <Field label="投递选项（JSON）" id="wh-options">
              <textarea
                id="wh-options"
                className={inputClass}
                rows={2}
                maxLength={10000}
                value={options}
                onChange={(event) => setOptions(event.target.value)}
              />
            </Field>
          </>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="去重冷却秒数" id="wh-cooldown">
            <Input
              id="wh-cooldown"
              type="number"
              min={0}
              max={86400}
              value={config.idempotency.cooldown_seconds}
              onChange={(event) =>
                setConfig({
                  ...config,
                  idempotency: { cooldown_seconds: Number(event.target.value) },
                })
              }
            />
          </Field>
          {(
            [
              ["requests_per_minute", "每分钟请求数", 10000],
              ["max_in_flight", "最大在途数", 1000],
              ["max_alerts", "单次最大告警数", 100],
            ] as const
          ).map(([key, label, max]) => (
            <Field key={key} label={label} id={`wh-${key}`}>
              <Input
                id={`wh-${key}`}
                type="number"
                min={1}
                max={max}
                value={config.limits[key]}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    limits: {
                      ...config.limits,
                      [key]: Number(event.target.value),
                    },
                  })
                }
              />
            </Field>
          ))}
        </div>
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
        预览映射
      </Button>
      {preview ? (
        <pre
          aria-label="映射预览"
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
