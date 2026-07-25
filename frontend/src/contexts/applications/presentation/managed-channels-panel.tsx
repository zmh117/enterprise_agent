import { useState, type FormEvent, type ReactNode } from "react"
import {
  BotIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  RotateCwIcon,
  Trash2Icon,
  WebhookIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  useCreateDingTalkChannel,
  useCreateWebhookChannel,
  useDeleteManagedChannel,
  useManagedChannels,
  useRestartManagedChannel,
  useSetManagedChannelEnabled,
  useUpdateDingTalkChannel,
  useWebhookConnectorOptions,
} from "@/contexts/applications/application/managed-channel-queries"
import type {
  DingTalkChannelInput,
  ManagedChannel,
  WebhookChannelInput,
  WebhookConnectorOption,
} from "@/contexts/applications/domain/managed-channel"
import { MutationError } from "@/contexts/applications/presentation/applications-page"
import { cn } from "@/lib/utils"
export function ManagedChannelsPanel() {
  const query = useManagedChannels()
  const webhookConnectorOptions = useWebhookConnectorOptions()
  const [dingTalkEditor, setDingTalkEditor] = useState<
    ManagedChannel | "create" | null
  >(null)
  const [webhookOpen, setWebhookOpen] = useState(false)

  return (
    <div className="space-y-5">
      <Card className="shadow-none">
        <CardHeader className="gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>渠道目录</CardTitle>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
              当前只管理钉钉应用机器人和受管 Webhook。启用且入口完整的渠道，
              才能在应用草稿的触发器绑定中选择。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => void query.refetch()}
              disabled={query.isFetching}
            >
              <RefreshCwIcon
                className={query.isFetching ? "animate-spin" : ""}
                aria-hidden="true"
              />
              刷新
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => setWebhookOpen(true)}
            >
              <WebhookIcon aria-hidden="true" />
              新建 Webhook
            </Button>
            <Button type="button" onClick={() => setDingTalkEditor("create")}>
              <PlusIcon aria-hidden="true" />
              新建钉钉机器人
            </Button>
          </div>
        </CardHeader>
      </Card>

      <MutationError error={query.error} />
      {query.isLoading ? (
        <Card className="shadow-none">
          <CardContent className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
            正在加载渠道……
          </CardContent>
        </Card>
      ) : query.data?.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {query.data.map((channel) => (
            <ManagedChannelCard
              key={`${channel.kind}-${channel.webhook_trigger_id ?? channel.id}`}
              channel={channel}
              onEdit={() => setDingTalkEditor(channel)}
            />
          ))}
        </div>
      ) : (
        <Card className="border-dashed shadow-none">
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            尚未配置渠道。新建钉钉机器人后，Runtime 会自动发现并建立连接。
          </CardContent>
        </Card>
      )}

      <DingTalkEditor
        key={
          dingTalkEditor === "create"
            ? "create"
            : (dingTalkEditor?.id ?? "closed")
        }
        open={dingTalkEditor !== null}
        channel={
          dingTalkEditor === "create"
            ? undefined
            : (dingTalkEditor ?? undefined)
        }
        onOpenChange={(open) => {
          if (!open) setDingTalkEditor(null)
        }}
      />
      <WebhookEditor
        open={webhookOpen}
        onOpenChange={setWebhookOpen}
        connectors={webhookConnectorOptions.data ?? []}
        connectorsLoading={webhookConnectorOptions.isLoading}
        connectorsError={webhookConnectorOptions.error}
      />
    </div>
  )
}

function ManagedChannelCard({
  channel,
  onEdit,
}: {
  channel: ManagedChannel
  onEdit: () => void
}) {
  const setEnabled = useSetManagedChannelEnabled()
  const restart = useRestartManagedChannel()
  const remove = useDeleteManagedChannel()
  const mutationError = setEnabled.error ?? restart.error ?? remove.error
  const status =
    channel.runtime?.status ?? (channel.enabled ? "READY" : "STOPPED")
  const dingTalk = channel.kind === "DINGTALK_APP_ROBOT"

  return (
    <Card className="shadow-none">
      <CardHeader className="gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {dingTalk ? (
                <BotIcon
                  className="size-4 text-indigo-600"
                  aria-hidden="true"
                />
              ) : (
                <WebhookIcon
                  className="size-4 text-emerald-600"
                  aria-hidden="true"
                />
              )}
              <CardTitle className="truncate text-base">
                {channel.name}
              </CardTitle>
              <Badge variant="outline">r{channel.revision}</Badge>
            </div>
            <p className="mt-2 font-mono text-xs break-all text-muted-foreground">
              {dingTalk
                ? channel.client_id
                : channel.code || channel.webhook_trigger_id}
            </p>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Badge variant={channel.enabled ? "default" : "secondary"}>
              {channel.enabled ? "已启用" : "已停用"}
            </Badge>
            <RuntimeBadge status={status} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid gap-3 text-xs sm:grid-cols-2">
          <Metadata
            label="类型"
            value={dingTalk ? "钉钉应用机器人" : "Webhook"}
          />
          <Metadata
            label={dingTalk ? "企业标识" : "入口路由"}
            value={
              dingTalk
                ? channel.tenant_code || "未配置"
                : channel.routing_key || "未发布"
            }
          />
          <Metadata
            label="最近消息"
            value={formatDate(channel.runtime?.last_message_at)}
          />
          <Metadata
            label="最近错误"
            value={channel.runtime?.last_error || "无"}
            danger={Boolean(channel.runtime?.last_error)}
          />
        </dl>
        {dingTalk ? (
          <>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onEdit}
              >
                <PencilIcon aria-hidden="true" />
                编辑
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={setEnabled.isPending}
                onClick={() =>
                  setEnabled.mutate({
                    channelId: channel.id,
                    revision: channel.revision,
                    enabled: !channel.enabled,
                  })
                }
              >
                {channel.enabled ? "停用" : "启用"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!channel.enabled || restart.isPending}
                onClick={() =>
                  restart.mutate({
                    channelId: channel.id,
                    revision: channel.revision,
                  })
                }
              >
                <RotateCwIcon aria-hidden="true" />
                重连
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={channel.enabled || remove.isPending}
                onClick={() => {
                  if (
                    window.confirm(
                      `确认删除渠道“${channel.name}”？被业务应用引用时服务端会拒绝删除。`
                    )
                  ) {
                    remove.mutate({
                      channelId: channel.id,
                      revision: channel.revision,
                    })
                  }
                }}
              >
                <Trash2Icon aria-hidden="true" />
                删除
              </Button>
            </div>
            <MutationError error={mutationError} />
          </>
        ) : (
          <p className="rounded-md border bg-muted/30 p-3 text-xs leading-5 text-muted-foreground">
            Webhook 继续使用现有受管 Webhook 生命周期；只有启用并发布完成后，
            才会出现在 Webhook Trigger 选择器中。
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function DingTalkEditor({
  open,
  channel,
  onOpenChange,
}: {
  open: boolean
  channel?: ManagedChannel
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateDingTalkChannel()
  const update = useUpdateDingTalkChannel(channel?.id ?? "")
  const [form, setForm] = useState(() => dingTalkForm(channel))
  const editorKey = channel ? `${channel.id}-${channel.revision}` : "create"

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        key={editorKey}
        className="w-full overflow-y-auto sm:max-w-xl"
      >
        <DingTalkEditorForm
          channel={channel}
          initialForm={form}
          setInitialForm={setForm}
          pending={create.isPending || update.isPending}
          error={create.error ?? update.error}
          onCancel={() => onOpenChange(false)}
          onSubmit={(value) => {
            const action = channel
              ? update.mutateAsync(value)
              : create.mutateAsync(value)
            void action.then(() => onOpenChange(false))
          }}
        />
      </SheetContent>
    </Sheet>
  )
}

function DingTalkEditorForm({
  channel,
  initialForm,
  setInitialForm,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  channel?: ManagedChannel
  initialForm: DingTalkChannelInput
  setInitialForm: (value: DingTalkChannelInput) => void
  pending: boolean
  error: unknown
  onCancel: () => void
  onSubmit: (value: DingTalkChannelInput) => void
}) {
  const form = channel
    ? {
        ...initialForm,
        expected_revision: channel.revision,
        enabled: channel.enabled,
        rotate_secret: Boolean(initialForm.client_secret),
      }
    : initialForm

  function submit(event: FormEvent) {
    event.preventDefault()
    onSubmit(form)
  }

  return (
    <form onSubmit={submit} className="flex min-h-full flex-col">
      <SheetHeader>
        <SheetTitle>{channel ? "编辑钉钉机器人" : "新建钉钉机器人"}</SheetTitle>
        <SheetDescription>
          Client Secret 保存后不再显示；编辑时留空表示保持原凭据。
        </SheetDescription>
      </SheetHeader>
      <div className="space-y-4 px-4">
        <EditorField label="渠道名称" htmlFor="dingtalk-name">
          <Input
            id="dingtalk-name"
            required
            minLength={2}
            maxLength={120}
            value={form.name}
            onChange={(event) =>
              setInitialForm({ ...initialForm, name: event.target.value })
            }
          />
        </EditorField>
        <EditorField label="Client ID / AppKey" htmlFor="dingtalk-client-id">
          <Input
            id="dingtalk-client-id"
            required
            maxLength={128}
            value={form.client_id}
            onChange={(event) =>
              setInitialForm({ ...initialForm, client_id: event.target.value })
            }
          />
        </EditorField>
        <EditorField
          label="企业标识（Corp / Tenant）"
          htmlFor="dingtalk-tenant"
        >
          <Input
            id="dingtalk-tenant"
            required
            maxLength={128}
            value={form.tenant_code}
            onChange={(event) =>
              setInitialForm({
                ...initialForm,
                tenant_code: event.target.value,
              })
            }
          />
        </EditorField>
        <EditorField
          label="Client Secret / AppSecret"
          htmlFor="dingtalk-secret"
        >
          <Input
            id="dingtalk-secret"
            type="password"
            required={!channel}
            maxLength={512}
            autoComplete="new-password"
            value={form.client_secret}
            placeholder={channel ? "留空表示不修改" : "请输入 Secret"}
            onChange={(event) =>
              setInitialForm({
                ...initialForm,
                client_secret: event.target.value,
              })
            }
          />
        </EditorField>
        <BooleanField
          id="dingtalk-private"
          label="允许私聊"
          checked={form.allow_private_chat}
          onChange={(checked) =>
            setInitialForm({ ...initialForm, allow_private_chat: checked })
          }
        />
        <BooleanField
          id="dingtalk-group"
          label="允许群聊"
          checked={form.allow_group_chat}
          onChange={(checked) =>
            setInitialForm({ ...initialForm, allow_group_chat: checked })
          }
        />
        <BooleanField
          id="dingtalk-require-at"
          label="群聊必须 @机器人"
          checked={form.require_group_at}
          onChange={(checked) =>
            setInitialForm({ ...initialForm, require_group_at: checked })
          }
        />
        {!channel ? (
          <BooleanField
            id="dingtalk-enabled"
            label="保存后立即启用"
            checked={form.enabled}
            onChange={(checked) =>
              setInitialForm({ ...initialForm, enabled: checked })
            }
          />
        ) : null}
        <MutationError error={error} />
      </div>
      <SheetFooter>
        <Button type="submit" disabled={pending}>
          {pending ? (
            <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
          ) : null}
          {channel ? "保存修改" : "创建渠道"}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          取消
        </Button>
      </SheetFooter>
    </form>
  )
}

function WebhookEditor({
  open,
  onOpenChange,
  connectors,
  connectorsLoading,
  connectorsError,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  connectors: WebhookConnectorOption[]
  connectorsLoading: boolean
  connectorsError: unknown
}) {
  const create = useCreateWebhookChannel()
  const [form, setForm] = useState<WebhookChannelInput>({
    code: "",
    name: "",
    trigger_type: "generic",
    connector_id: connectors[0]?.id ?? "",
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      {
        ...form,
        connector_id: form.connector_id || connectors[0]?.id || "",
      },
      {
        onSuccess: () => {
          setForm({
            code: "",
            name: "",
            trigger_type: "generic",
            connector_id: connectors[0]?.id ?? "",
          })
          onOpenChange(false)
        },
      }
    )
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <form onSubmit={submit} className="flex min-h-full flex-col">
          <SheetHeader>
            <SheetTitle>新建受管 Webhook</SheetTitle>
            <SheetDescription>
              这里只登记受管入口定义，不提供任意 HTTP 地址。完成现有 Webhook
              配置和发布后，入口才能绑定到应用。
            </SheetDescription>
          </SheetHeader>
          <div className="space-y-4 px-4">
            <EditorField label="Webhook 编码" htmlFor="webhook-code">
              <Input
                id="webhook-code"
                required
                pattern="[a-z][a-z0-9-]{2,63}"
                value={form.code}
                onChange={(event) =>
                  setForm({ ...form, code: event.target.value })
                }
                placeholder="ones-event"
              />
            </EditorField>
            <EditorField label="Webhook 名称" htmlFor="webhook-name">
              <Input
                id="webhook-name"
                required
                maxLength={200}
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
              />
            </EditorField>
            <EditorField label="Webhook 类型" htmlFor="webhook-type">
              <select
                id="webhook-type"
                className={selectClass}
                value={form.trigger_type}
                onChange={(event) =>
                  setForm({
                    ...form,
                    trigger_type: event.target
                      .value as WebhookChannelInput["trigger_type"],
                  })
                }
              >
                <option value="generic">通用 JSON</option>
                <option value="grafana">Grafana 告警</option>
              </select>
            </EditorField>
            <EditorField label="入口 Connector" htmlFor="webhook-connector">
              <select
                id="webhook-connector"
                required
                className={selectClass}
                value={form.connector_id || connectors[0]?.id || ""}
                onChange={(event) =>
                  setForm({ ...form, connector_id: event.target.value })
                }
              >
                <option value="">请选择现有 Webhook Connector</option>
                {connectors.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.connector_type}
                  </option>
                ))}
              </select>
            </EditorField>
            {connectorsLoading ? (
              <p className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
                正在加载 Webhook 入口 Connector……
              </p>
            ) : connectors.length === 0 && !connectorsError ? (
              <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
                当前没有可复用的 Webhook 入口 Connector，无法新建。
              </p>
            ) : null}
            <MutationError error={connectorsError ?? create.error} />
          </div>
          <SheetFooter>
            <Button
              type="submit"
              disabled={
                create.isPending ||
                connectorsLoading ||
                Boolean(connectorsError) ||
                connectors.length === 0
              }
            >
              {create.isPending ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : null}
              创建 Webhook 定义
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  )
}

function RuntimeBadge({ status }: { status: string }) {
  const ready = status === "READY"
  const bad = ["AUTH_FAILED", "ERROR", "STALE"].includes(status)
  return (
    <Badge variant={bad ? "destructive" : ready ? "default" : "secondary"}>
      {runtimeLabel(status)}
    </Badge>
  )
}

function Metadata({
  label,
  value,
  danger = false,
}: {
  label: string
  value: string
  danger?: boolean
}) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "mt-1 font-medium break-words",
          danger && "text-destructive"
        )}
      >
        {value}
      </dd>
    </div>
  )
}

function EditorField({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: ReactNode
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  )
}

function BooleanField({
  id,
  label,
  checked,
  onChange,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label
      htmlFor={id}
      className="flex cursor-pointer items-center justify-between rounded-md border p-3 text-sm"
    >
      <span>{label}</span>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 accent-primary"
      />
    </label>
  )
}

function dingTalkForm(channel?: ManagedChannel): DingTalkChannelInput {
  return {
    expected_revision: channel?.revision ?? 0,
    name: channel?.name ?? "",
    client_id: channel?.client_id ?? "",
    client_secret: "",
    tenant_code: channel?.tenant_code ?? "default",
    allow_private_chat: channel?.capabilities.private_chat ?? true,
    allow_group_chat: channel?.capabilities.group_chat ?? true,
    require_group_at: channel?.capabilities.require_group_at ?? true,
    enabled: channel?.enabled ?? false,
    rotate_secret: false,
  }
}

function runtimeLabel(status: string) {
  const labels: Record<string, string> = {
    READY: "已就绪",
    REGISTERED: "已注册",
    CONNECTED: "已连接，待注册",
    STARTING: "连接中",
    RECONNECTING: "重连中",
    AUTH_FAILED: "认证失败",
    ERROR: "运行异常",
    STALE: "状态过期",
    STOPPED: "已停止",
  }
  return labels[status] ?? status
}

function formatDate(value?: string | null) {
  if (!value) return "暂无"
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "medium",
        hour12: false,
      }).format(parsed)
}

const selectClass =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
