import { useState, type FormEvent, type ReactNode } from "react"
import {
  ArchiveIcon,
  BotIcon,
  Building2Icon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  RotateCwIcon,
  ShieldCheckIcon,
  Trash2Icon,
  WebhookIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
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
  useCreateDingTalkEnterprise,
  useCreateDingTalkChannel,
  useCreateWebhookChannel,
  useDeleteManagedChannel,
  useDingTalkEnterprise,
  useDingTalkEnterprises,
  useGovernDingTalkEnterprise,
  useManagedChannels,
  useRestartManagedChannel,
  useRenameDingTalkEnterprise,
  useSetManagedChannelEnabled,
  useTestManagedChannel,
  useUpdateDingTalkChannel,
  useWebhookConnectorOptions,
} from "@/contexts/applications/application/managed-channel-queries"
import type {
  DingTalkChannelInput,
  DingTalkEnterprise,
  ManagedChannel,
  WebhookChannelInput,
  WebhookConnectorOption,
} from "@/contexts/applications/domain/managed-channel"
import { MutationError } from "@/contexts/applications/presentation/applications-page"
import { cn } from "@/lib/utils"
export function ManagedChannelsPanel() {
  const query = useManagedChannels()
  const enterprises = useDingTalkEnterprises()
  const webhookConnectorOptions = useWebhookConnectorOptions()
  const [dingTalkEditor, setDingTalkEditor] = useState<
    ManagedChannel | "create" | null
  >(null)
  const [webhookOpen, setWebhookOpen] = useState(false)
  const [enterpriseEditor, setEnterpriseEditor] = useState<
    DingTalkEnterprise | "create" | null
  >(null)
  const [enterpriseGovernance, setEnterpriseGovernance] = useState<{
    enterpriseId: string
    action: "disable" | "archive" | "restore"
  } | null>(null)

  return (
    <div className="space-y-5">
      <DingTalkEnterpriseSection
        enterprises={enterprises.data ?? []}
        loading={enterprises.isLoading}
        error={enterprises.error}
        onCreate={() => setEnterpriseEditor("create")}
        onRename={setEnterpriseEditor}
        onGovern={(enterprise, action) =>
          setEnterpriseGovernance({ enterpriseId: enterprise.id, action })
        }
      />
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
      <DingTalkEnterpriseEditor
        key={
          enterpriseEditor === "create"
            ? "enterprise-create"
            : (enterpriseEditor?.id ?? "enterprise-closed")
        }
        open={enterpriseEditor !== null}
        enterprise={
          enterpriseEditor === "create"
            ? undefined
            : (enterpriseEditor ?? undefined)
        }
        onOpenChange={(open) => {
          if (!open) setEnterpriseEditor(null)
        }}
      />
      <DingTalkEnterpriseGovernanceSheet
        selection={enterpriseGovernance}
        onOpenChange={(open) => {
          if (!open) setEnterpriseGovernance(null)
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

function DingTalkEnterpriseSection({
  enterprises,
  loading,
  error,
  onCreate,
  onRename,
  onGovern,
}: {
  enterprises: DingTalkEnterprise[]
  loading: boolean
  error: unknown
  onCreate: () => void
  onRename: (enterprise: DingTalkEnterprise) => void
  onGovern: (
    enterprise: DingTalkEnterprise,
    action: "disable" | "archive" | "restore"
  ) => void
}) {
  return (
    <Card className="shadow-none">
      <CardHeader className="gap-4 border-b sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Building2Icon
              className="size-4 text-indigo-600"
              aria-hidden="true"
            />
            <CardTitle>钉钉企业</CardTitle>
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            企业保存钉钉组织边界；Corp ID
            只能由首条受信测试消息确认，不能手工填写或修改。
          </p>
        </div>
        <Button type="button" variant="outline" onClick={onCreate}>
          <PlusIcon aria-hidden="true" />
          新建钉钉企业
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <MutationError error={error} />
        {loading ? (
          <LoadingLine label="正在加载钉钉企业……" />
        ) : enterprises.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {enterprises.map((enterprise) => (
              <article key={enterprise.id} className="rounded-xl border p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium">{enterprise.name}</p>
                    <p className="mt-1 font-mono text-xs break-all text-muted-foreground">
                      {enterprise.corp_id || "Corp ID 等待测试消息确认"}
                    </p>
                  </div>
                  <Badge variant={enterpriseStatusVariant(enterprise.status)}>
                    {enterpriseStatusLabel(enterprise.status)}
                  </Badge>
                </div>
                <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
                  <Metadata
                    label="应用连接"
                    value={`${enterprise.connector_count} 个`}
                  />
                  <Metadata
                    label="已启用连接"
                    value={`${enterprise.enabled_connector_count} 个`}
                  />
                  <Metadata
                    label="验证时间"
                    value={formatDate(enterprise.verified_at)}
                  />
                  <Metadata
                    label="Revision"
                    value={`r${enterprise.revision}`}
                  />
                </dl>
                {enterprise.status === "PENDING_VERIFICATION" ? (
                  <p className="mt-3 rounded-md bg-amber-50 p-2 text-xs leading-5 text-amber-950">
                    创建并启用该企业的首个应用连接后，请向机器人发送测试消息完成验证。
                  </p>
                ) : null}
                <div className="mt-4 flex flex-wrap gap-2">
                  {enterprise.status !== "ARCHIVED" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => onRename(enterprise)}
                    >
                      <PencilIcon aria-hidden="true" />
                      改名
                    </Button>
                  ) : null}
                  {enterprise.status === "ACTIVE" ||
                  enterprise.status === "PENDING_VERIFICATION" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => onGovern(enterprise, "disable")}
                    >
                      停用企业
                    </Button>
                  ) : null}
                  {enterprise.status === "DISABLED" ? (
                    <>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => onGovern(enterprise, "restore")}
                      >
                        恢复并重新验证
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => onGovern(enterprise, "archive")}
                      >
                        <ArchiveIcon aria-hidden="true" />
                        归档
                      </Button>
                    </>
                  ) : null}
                  {enterprise.status === "ARCHIVED" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => onGovern(enterprise, "restore")}
                    >
                      恢复并重新验证
                    </Button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
            尚未创建钉钉企业。请先创建待验证企业，再配置第一个钉钉应用连接。
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function DingTalkEnterpriseEditor({
  open,
  enterprise,
  onOpenChange,
}: {
  open: boolean
  enterprise?: DingTalkEnterprise
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateDingTalkEnterprise()
  const rename = useRenameDingTalkEnterprise()
  const [name, setName] = useState(enterprise?.name ?? "")
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const options = { onSuccess: () => onOpenChange(false) }
    if (enterprise) {
      rename.mutate(
        {
          enterpriseId: enterprise.id,
          name: name.trim(),
          expectedRevision: enterprise.revision,
        },
        options
      )
    } else {
      create.mutate(name.trim(), options)
    }
  }
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-lg">
        <form className="flex min-h-full flex-col" onSubmit={submit}>
          <SheetHeader>
            <SheetTitle>
              {enterprise ? "修改钉钉企业名称" : "新建钉钉企业"}
            </SheetTitle>
            <SheetDescription>
              这里只设置平台内名称。Corp ID
              将由应用连接收到的首条受信测试消息确认。
            </SheetDescription>
          </SheetHeader>
          <div className="space-y-3 px-4">
            <EditorField label="企业名称" htmlFor="dingtalk-enterprise-name">
              <Input
                id="dingtalk-enterprise-name"
                required
                maxLength={120}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </EditorField>
            <MutationError error={create.error ?? rename.error} />
          </div>
          <SheetFooter>
            <Button
              type="submit"
              disabled={!name.trim() || create.isPending || rename.isPending}
            >
              {enterprise ? "保存名称" : "创建待验证企业"}
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

function DingTalkEnterpriseGovernanceSheet({
  selection,
  onOpenChange,
}: {
  selection: {
    enterpriseId: string
    action: "disable" | "archive" | "restore"
  } | null
  onOpenChange: (open: boolean) => void
}) {
  const detail = useDingTalkEnterprise(selection?.enterpriseId ?? "")
  const govern = useGovernDingTalkEnterprise()
  const action = selection?.action
  const enterprise = detail.data
  const title =
    action === "disable"
      ? "停用钉钉企业"
      : action === "archive"
        ? "归档钉钉企业"
        : "恢复钉钉企业并重新验证"
  return (
    <Sheet open={Boolean(selection)} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>
            {action === "restore"
              ? "恢复后企业回到待验证状态，必须重新通过受信测试消息确认 Corp ID。"
              : "请先核对受影响的应用连接和业务应用；历史发布记录不会被删除。"}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4">
          {detail.isLoading ? <LoadingLine label="正在核对影响范围……" /> : null}
          {enterprise ? (
            <>
              <div className="rounded-lg border p-3 text-sm">
                <p className="font-medium">{enterprise.name}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {enterpriseStatusLabel(enterprise.status)} · r
                  {enterprise.revision}
                </p>
              </div>
              <div>
                <p className="text-sm font-medium">影响范围</p>
                {enterprise.impacts?.length ? (
                  <div className="mt-2 space-y-2">
                    {enterprise.impacts.map((impact, index) => (
                      <div
                        key={`${impact.connector_id}:${impact.application_id}:${index}`}
                        className="rounded-md border p-3 text-xs"
                      >
                        <p className="font-medium">
                          {impact.connector_name} ·{" "}
                          {impact.connector_enabled ? "已启用" : "已停用"}
                        </p>
                        <p className="mt-1 text-muted-foreground">
                          {impact.application_name
                            ? `业务应用：${impact.application_name}${impact.application_revision ? ` · r${impact.application_revision}` : ""}`
                            : "未被活动业务应用版本引用"}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-muted-foreground">
                    没有应用连接或活动业务应用引用。
                  </p>
                )}
              </div>
            </>
          ) : null}
          <MutationError error={detail.error ?? govern.error} />
        </div>
        <SheetFooter>
          <Button
            type="button"
            variant={action === "restore" ? "default" : "destructive"}
            disabled={!enterprise || !action || govern.isPending}
            onClick={() => {
              if (!enterprise || !action) return
              govern.mutate(
                {
                  enterpriseId: enterprise.id,
                  action,
                  expectedRevision: enterprise.revision,
                },
                { onSuccess: () => onOpenChange(false) }
              )
            }}
          >
            {title}
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

function LoadingLine({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
      {label}
    </p>
  )
}

function ManagedChannelCard({
  channel,
  onEdit,
}: {
  channel: ManagedChannel
  onEdit: () => void
}) {
  const [deleteOpen, setDeleteOpen] = useState(false)
  const setEnabled = useSetManagedChannelEnabled()
  const restart = useRestartManagedChannel()
  const testConfiguration = useTestManagedChannel()
  const remove = useDeleteManagedChannel()
  const mutationError =
    setEnabled.error ?? restart.error ?? testConfiguration.error ?? remove.error
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
            label={dingTalk ? "钉钉企业" : "入口路由"}
            value={
              dingTalk
                ? channel.enterprise?.name || "未配置"
                : channel.routing_key || "未发布"
            }
          />
          {dingTalk ? (
            <Metadata
              label="企业状态"
              value={enterpriseStatusLabel(channel.enterprise?.status)}
              danger={
                channel.enterprise?.status === "DISABLED" ||
                channel.enterprise?.status === "ARCHIVED"
              }
            />
          ) : null}
          <Metadata label="连接运行状态" value={runtimeLabel(status)} />
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
        {dingTalk &&
        channel.enterprise?.status === "PENDING_VERIFICATION" &&
        status === "CONNECTED" ? (
          <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs leading-5 text-amber-950">
            已连接，等待企业验证。请在钉钉中向该应用发送一条测试消息，平台会校验并固化
            Corp ID；验证消息不会创建 Agent 任务。
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={testConfiguration.isPending}
            onClick={() => testConfiguration.mutate(channel.id)}
          >
            {testConfiguration.isPending ? (
              <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
            ) : (
              <ShieldCheckIcon aria-hidden="true" />
            )}
            测试配置
          </Button>
          {testConfiguration.data ? (
            <span className="text-xs text-emerald-700">
              {testConfiguration.data.summary}
            </span>
          ) : null}
        </div>
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
                onClick={() => setDeleteOpen(true)}
              >
                <Trash2Icon aria-hidden="true" />
                删除
              </Button>
            </div>
            <MutationError error={mutationError} />
            <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>删除钉钉应用连接？</AlertDialogTitle>
                  <AlertDialogDescription>
                    将删除“{channel.name}
                    ”的当前连接配置；历史发布记录不会被删除。
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="rounded-lg border p-3 text-sm">
                  <p className="font-medium">业务应用引用</p>
                  {channel.references.length ? (
                    <ul className="mt-2 space-y-1 text-muted-foreground">
                      {channel.references.map((reference, index) => (
                        <li
                          key={`${reference.application_code}-${reference.application_revision}-${reference.trigger_type}-${index}`}
                        >
                          {reference.application_name ||
                            reference.application_code}
                          {` · r${reference.application_revision} · ${reference.trigger_type}`}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-muted-foreground">
                      当前没有业务应用草稿或发布版本引用此连接。
                    </p>
                  )}
                </div>
                {channel.references.length ? (
                  <p className="text-sm text-destructive">
                    请先从上述业务应用中移除此连接并重新发布，之后才能删除。
                  </p>
                ) : null}
                <AlertDialogFooter>
                  <AlertDialogCancel>取消</AlertDialogCancel>
                  <AlertDialogAction
                    variant="destructive"
                    disabled={channel.references.length > 0 || remove.isPending}
                    onClick={() =>
                      remove.mutate(
                        {
                          channelId: channel.id,
                          revision: channel.revision,
                        },
                        { onSuccess: () => setDeleteOpen(false) }
                      )
                    }
                  >
                    确认删除
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
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
  const enterprises = useDingTalkEnterprises()
  const createEnterprise = useCreateDingTalkEnterprise()
  const [newEnterpriseName, setNewEnterpriseName] = useState("")
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
          {channel?.runtime?.status === "MISCONFIGURED"
            ? " 当前凭据不可用，请填写新 Secret 保存，再执行配置测试。"
            : ""}
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
        <EditorField label="钉钉企业" htmlFor="dingtalk-enterprise">
          <select
            id="dingtalk-enterprise"
            required
            className={selectClass}
            value={form.dingtalk_enterprise_id}
            onChange={(event) =>
              setInitialForm({
                ...initialForm,
                dingtalk_enterprise_id: event.target.value,
              })
            }
          >
            <option value="">请选择钉钉企业</option>
            {enterprises.data
              ?.filter(
                (enterprise) =>
                  enterprise.status === "PENDING_VERIFICATION" ||
                  enterprise.status === "ACTIVE" ||
                  enterprise.id === channel?.enterprise?.id
              )
              .map((enterprise) => (
                <option key={enterprise.id} value={enterprise.id}>
                  {enterprise.name} · {enterpriseStatusLabel(enterprise.status)}
                </option>
              ))}
          </select>
        </EditorField>
        {!channel ? (
          <div className="space-y-2 rounded-lg border bg-muted/20 p-3">
            <Label htmlFor="new-dingtalk-enterprise">
              没有可选企业？先创建待验证企业
            </Label>
            <div className="flex gap-2">
              <Input
                id="new-dingtalk-enterprise"
                value={newEnterpriseName}
                maxLength={120}
                onChange={(event) => setNewEnterpriseName(event.target.value)}
                placeholder="例如：研发中心钉钉企业"
              />
              <Button
                type="button"
                variant="outline"
                disabled={
                  !newEnterpriseName.trim() || createEnterprise.isPending
                }
                onClick={() => {
                  void createEnterprise
                    .mutateAsync(newEnterpriseName.trim())
                    .then((enterprise) => {
                      setInitialForm({
                        ...initialForm,
                        dingtalk_enterprise_id: enterprise.id,
                      })
                      setNewEnterpriseName("")
                    })
                    .catch(() => undefined)
                }}
              >
                创建企业
              </Button>
            </div>
            <MutationError
              error={enterprises.error ?? createEnterprise.error}
            />
          </div>
        ) : null}
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
        <EditorField
          label="企业机器人 Code"
          htmlFor="dingtalk-enterprise-robot-code"
        >
          <Input
            id="dingtalk-enterprise-robot-code"
            maxLength={128}
            value={form.enterprise_robot_code}
            placeholder="启用机器人个人/群消息 Tool 时必填"
            onChange={(event) =>
              setInitialForm({
                ...initialForm,
                enterprise_robot_code: event.target.value,
              })
            }
          />
          <p className="text-xs leading-5 text-muted-foreground">
            对应钉钉官方 MCP 的 ROBOT_CODE，用于企业机器人个人/群消息；不是工作通知
            Agent ID，也不是 Secret。
          </p>
        </EditorField>
        <EditorField
          label="工作通知 Agent ID"
          htmlFor="dingtalk-work-notification-agent-id"
        >
          <Input
            id="dingtalk-work-notification-agent-id"
            type="number"
            min={1}
            step={1}
            value={form.work_notification_agent_id ?? ""}
            placeholder={
              channel?.work_notification_agent_id_configured
                ? `已配置 ${channel.work_notification_agent_id_hint}，留空表示不修改`
                : "可选；启用工作通知 Tool 时必填"
            }
            onChange={(event) =>
              setInitialForm({
                ...initialForm,
                work_notification_agent_id: event.target.value
                  ? Number(event.target.value)
                  : null,
              })
            }
          />
          <p className="text-xs leading-5 text-muted-foreground">
            仅用于当前用户本人的工作通知；保存后只显示尾号，不作为 Secret
            存储。
          </p>
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
  const bad = ["AUTH_FAILED", "ERROR", "MISCONFIGURED", "STALE"].includes(
    status
  )
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
    dingtalk_enterprise_id: channel?.enterprise?.id ?? "",
    allow_private_chat: channel?.capabilities.private_chat ?? true,
    allow_group_chat: channel?.capabilities.group_chat ?? true,
    require_group_at: channel?.capabilities.require_group_at ?? true,
    work_notification_agent_id: null,
    enterprise_robot_code: channel?.enterprise_robot_code ?? "",
    enabled: channel?.enabled ?? false,
    rotate_secret: false,
  }
}

function runtimeLabel(status: string) {
  const labels: Record<string, string> = {
    READY: "已就绪",
    REGISTERED: "已注册",
    CONNECTED: "已连接",
    STARTING: "连接中",
    RECONNECTING: "重连中",
    AUTH_FAILED: "认证失败",
    ERROR: "运行异常",
    MISCONFIGURED: "配置异常",
    STALE: "状态过期",
    STOPPED: "已停止",
  }
  return labels[status] ?? status
}

function enterpriseStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    PENDING_VERIFICATION: "待企业验证",
    ACTIVE: "已验证",
    DISABLED: "已停用",
    ARCHIVED: "已归档",
    UNASSIGNED: "未关联企业",
  }
  return labels[status ?? ""] ?? status ?? "企业状态不可用"
}

function enterpriseStatusVariant(status: DingTalkEnterprise["status"]) {
  if (status === "ACTIVE") return "default" as const
  if (status === "DISABLED" || status === "ARCHIVED") {
    return "destructive" as const
  }
  return "secondary" as const
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
