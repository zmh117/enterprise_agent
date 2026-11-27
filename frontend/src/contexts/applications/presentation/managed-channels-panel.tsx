import { ArchiveAction } from "@/shared/presentation/archive-action"
import { apiRequest } from "@/shared/api/api-client"
import {
  ListPage,
  ListSearch,
  ListResults,
  ListStatus,
  ListEmpty,
  RefreshList,
  CatalogPager,
  ExpandableListRow,
  ListStatusFilter,
} from "@/shared/presentation/list-page"
import {
  useListNavigation,
  matchesListSearch,
  catalogPage,
} from "@/shared/presentation/list-navigation"
import {
  Table,
  TableHeader,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { useState, type FormEvent, type ReactNode } from "react"
import {
  ArchiveIcon,
  BotIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
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
import { FormDialog, FormDialogCancel } from "@/shared/presentation/form-dialog"
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
  useDisableWebhook,
  useTestManagedChannel,
  useUpdateDingTalkChannel,
} from "@/contexts/applications/application/managed-channel-queries"
import type {
  DingTalkChannelInput,
  DingTalkEnterprise,
  ManagedChannel,
  WebhookChannelInput,
} from "@/contexts/applications/domain/managed-channel"
import { MutationError } from "@/contexts/applications/presentation/applications-page"
import { cn } from "@/lib/utils"
import { WebhookSettings } from "@/contexts/applications/presentation/webhook-settings"
export function ManagedChannelsPanel() {
  const [webhookCode, setWebhookCode] = useState<string | null>(null)
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

  const list = useListNavigation()
  const enterpriseView = list.params.get("tab") === "enterprises"
  const q = list.params.get("q") ?? ""
  const status = list.params.get("status") ?? ""
  const query = useManagedChannels(!enterpriseView, status === "archived")
  const enterprises = useDingTalkEnterprises(status === "ARCHIVED")
  const clear = () => list.filter({ q: "", status: "" })
  const channelKinds = {
    BROWSER_EXTENSION: "浏览器插件",
    DINGTALK_APP_ROBOT: "钉钉应用机器人",
    WEBHOOK: "Webhook",
  }
  const channels = catalogPage(
    (query.data ?? []).filter(
      (c) =>
        matchesListSearch(
          q,
          c.name,
          c.code,
          c.client_id,
          c.enterprise?.name,
          channelKinds[c.kind]
        ) &&
        (!status ||
          (c.archived ? "archived" : c.enabled ? "enabled" : "disabled") ===
            status)
    ),
    list.page
  )
  const companies = catalogPage(
    (enterprises.data ?? []).filter(
      (e) =>
        matchesListSearch(q, e.name, e.corp_id) &&
        (status ? status === e.status : e.status !== "ARCHIVED")
    ),
    list.page
  )
  const active = enterpriseView ? enterprises : query
  const result = enterpriseView ? companies : channels
  return (
    <ListPage
      title="渠道与触发器"
      actions={
        <>
          <RefreshList
            refresh={() => void active.refetch()}
            busy={active.isFetching}
          />
          {enterpriseView ? (
            <Button onClick={() => setEnterpriseEditor("create")}>
              <PlusIcon />
              新建钉钉企业
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => setWebhookOpen(true)}>
                新建 Webhook
              </Button>
              <Button onClick={() => setDingTalkEditor("create")}>
                <PlusIcon />
                新建钉钉机器人
              </Button>
            </>
          )}
        </>
      }
    >
      <Tabs
        value={enterpriseView ? "enterprises" : "channels"}
        onValueChange={(tab) =>
          list.filter({
            tab: tab === "enterprises" ? "enterprises" : "",
            q: "",
            status: "",
          })
        }
      >
        <TabsList variant="line" aria-label="渠道管理">
          <TabsTrigger value="channels">渠道目录</TabsTrigger>
          <TabsTrigger value="enterprises">钉钉企业</TabsTrigger>
        </TabsList>
        <TabsContent
          key={enterpriseView ? "enterprises" : "channels"}
          value={enterpriseView ? "enterprises" : "channels"}
          className="grid min-w-0 gap-4 pt-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <ListSearch
              label={enterpriseView ? "搜索钉钉企业" : "搜索渠道"}
              placeholder={
                enterpriseView
                  ? "搜索企业名称或 Corp ID"
                  : "搜索渠道名称、标识或类型"
              }
              value={q}
              onCommit={(q) => list.filter({ q })}
            />
            {enterpriseView ? (
              <select
                aria-label="企业状态"
                className="h-8 rounded-lg border bg-background px-2 text-sm"
                value={status}
                onChange={(e) => list.filter({ status: e.target.value })}
              >
                <option value="">全部状态</option>
                {["PENDING_VERIFICATION", "ACTIVE", "DISABLED", "ARCHIVED"].map(
                  (v) => (
                    <option key={v} value={v}>
                      {enterpriseStatusLabel(v)}
                    </option>
                  )
                )}
              </select>
            ) : (
              <ListStatusFilter
                archived
                value={status}
                onChange={(status) => list.filter({ status })}
              />
            )}
            {(q || status) && (
              <Button variant="ghost" onClick={clear}>
                重置
              </Button>
            )}
          </div>
          {active.isError ? (
            <MutationError error={active.error} />
          ) : active.isLoading ? (
            <LoadingLine label="正在加载…" />
          ) : (
            <ListResults>
              {!result.total ? (
                <ListEmpty
                  title={
                    q || status
                      ? "没有符合条件的记录"
                      : enterpriseView
                        ? "尚未创建钉钉企业"
                        : "尚未配置渠道"
                  }
                  clear={q || status ? clear : undefined}
                />
              ) : enterpriseView ? (
                <DingTalkEnterpriseSection
                  enterprises={companies.rows}
                  onRename={setEnterpriseEditor}
                  onGovern={(e, action) =>
                    setEnterpriseGovernance({ enterpriseId: e.id, action })
                  }
                />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>渠道名称</TableHead>
                      <TableHead className="hidden sm:table-cell">
                        类型
                      </TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>运行状态</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {channels.rows.map((c) => (
                      <ExpandableListRow
                        key={c.id}
                        name={c.name}
                        meta={c.code || c.client_id}
                        columns={4}
                        cells={
                          <>
                            <TableCell className="hidden sm:table-cell">
                              {channelKinds[c.kind]}
                            </TableCell>
                            <TableCell>
                              <ListStatus
                                status={
                                  c.archived
                                    ? "archived"
                                    : c.enabled
                                      ? "enabled"
                                      : "disabled"
                                }
                              />
                            </TableCell>
                            <TableCell>
                              {c.kind === "BROWSER_EXTENSION" ? (
                                "—"
                              ) : (
                                <RuntimeBadge
                                  status={
                                    c.runtime?.status ??
                                    (c.enabled ? "READY" : "STOPPED")
                                  }
                                />
                              )}
                            </TableCell>
                          </>
                        }
                      >
                        {c.kind === "BROWSER_EXTENSION" ? (
                          <BrowserChannelCard channel={c} />
                        ) : (
                          <ManagedChannelCard
                            channel={c}
                            onEdit={() =>
                              c.kind === "WEBHOOK"
                                ? setWebhookCode(c.code ?? null)
                                : setDingTalkEditor(c)
                            }
                          />
                        )}
                      </ExpandableListRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              <CatalogPager result={result} onPage={list.numberedPage} />
            </ListResults>
          )}
        </TabsContent>
      </Tabs>
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
      {webhookOpen && (
        <WebhookEditor
          onOpenChange={setWebhookOpen}
          onCreated={setWebhookCode}
        />
      )}
      <WebhookSettings
        code={webhookCode}
        onClose={() => setWebhookCode(null)}
      />
    </ListPage>
  )
}

function DingTalkEnterpriseSection({
  enterprises,
  onRename,
  onGovern,
}: {
  enterprises: DingTalkEnterprise[]
  onRename: (enterprise: DingTalkEnterprise) => void
  onGovern: (
    enterprise: DingTalkEnterprise,
    action: "disable" | "archive" | "restore"
  ) => void
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>企业名称</TableHead>
          <TableHead>状态</TableHead>
          <TableHead>已启用 / 全部连接</TableHead>
          <TableHead className="hidden sm:table-cell">验证时间</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {enterprises.map((enterprise) => (
          <ExpandableListRow
            key={enterprise.id}
            name={enterprise.name}
            meta={enterprise.corp_id || "Corp ID 待验证"}
            columns={4}
            cells={
              <>
                <TableCell>
                  <Badge variant={enterpriseStatusVariant(enterprise.status)}>
                    {enterpriseStatusLabel(enterprise.status)}
                  </Badge>
                </TableCell>
                <TableCell>
                  {enterprise.enabled_connector_count} /{" "}
                  {enterprise.connector_count}
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  {formatDate(enterprise.verified_at)}
                </TableCell>
              </>
            }
          >
            <div className="space-y-2 p-2">
              <p className="text-xs text-muted-foreground">
                修订 r{enterprise.revision} · 验证时间{" "}
                {formatDate(enterprise.verified_at)}
              </p>
              {enterprise.status === "PENDING_VERIFICATION" && (
                <p className="text-sm">
                  启用首个应用连接后，向机器人发送测试消息以验证企业。
                </p>
              )}
              <div className="flex flex-wrap gap-2">
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
            </div>
          </ExpandableListRow>
        ))}
      </TableBody>
    </Table>
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
    open && (
      <FormDialog
        asSheet={Boolean(enterprise)}
        title={enterprise ? "修改钉钉企业名称" : "新建钉钉企业"}
        description="这里只设置平台内名称。Corp ID 将由应用连接收到的首条受信测试消息确认。"
        onClose={() => onOpenChange(false)}
        pending={create.isPending || rename.isPending}
      >
        <form className="grid gap-5" onSubmit={submit}>
          <div className="space-y-3">
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
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              type="submit"
              disabled={!name.trim() || create.isPending || rename.isPending}
            >
              {enterprise ? "保存名称" : "创建待验证企业"}
            </Button>
            <FormDialogCancel disabled={create.isPending || rename.isPending} />
          </div>
        </form>
      </FormDialog>
    )
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

function BrowserChannelCard({ channel }: { channel: ManagedChannel }) {
  const toggle = useSetManagedChannelEnabled()
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle>{channel.name}</CardTitle>
        <p className="text-sm text-muted-foreground">用户用系统账号登录插件，在获准使用的应用中提问。</p>
      </CardHeader>
      <CardContent className="flex items-center gap-3">
        <Badge variant={channel.enabled ? "default" : "secondary"}>
          {channel.enabled ? "已启用" : "已停用"}
        </Badge>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={toggle.isPending}
          onClick={() =>
            toggle.mutate({
              channelId: channel.id,
              revision: channel.revision,
              enabled: !channel.enabled,
            })
          }
        >
          {channel.enabled ? "停用" : "启用"}
        </Button>
        <MutationError error={toggle.error} />
      </CardContent>
    </Card>
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
  const disableWebhook = useDisableWebhook()
  const restart = useRestartManagedChannel()
  const testConfiguration = useTestManagedChannel()
  const remove = useDeleteManagedChannel()
  const mutationError =
    setEnabled.error ?? disableWebhook.error ?? restart.error ?? testConfiguration.error ?? remove.error
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
              {channel.archived ? "已归档" : channel.enabled ? "已启用" : "已停用"}
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
        {!channel.archived && dingTalk ? (
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
        ) : null}
        {channel.archived ? null : dingTalk ? (
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
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={onEdit}>
              配置 Webhook
            </Button>
            {channel.enabled ? (
              <Button
                type="button"
                variant="outline"
                disabled={disableWebhook.isPending}
                onClick={() => disableWebhook.mutate(channel)}
              >
                停用 Webhook
              </Button>
            ) : null}
          </div>
        )}
        {!channel.archived &&
          (!channel.enabled || (!dingTalk && channel.published === false)) && (
            <ArchiveAction
              name={channel.name}
              queryKey={["managed-channels"]}
              archive={() =>
                apiRequest(
                  `/api/admin/managed-channels/${encodeURIComponent(channel.id)}/archive${channel.kind === "WEBHOOK" ? "?webhook_code=" + encodeURIComponent(channel.code ?? "") : ""}`,
                  {
                    method: "POST",
                    body: { expected_revision: channel.revision },
                  }
                )
              }
            />
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
    open && (
      <DingTalkEditorForm
        key={editorKey}
        channel={channel}
        initialForm={form}
        setInitialForm={setForm}
        pending={create.isPending || update.isPending}
        error={create.error ?? update.error}
        onCancel={() => onOpenChange(false)}
        onSubmit={(value) => {
          const options = { onSuccess: () => onOpenChange(false) }
          if (channel) update.mutate(value, options)
          else create.mutate(value, options)
        }}
      />
    )
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
    <FormDialog
      title={channel ? "编辑钉钉机器人" : "新建钉钉机器人"}
      description={
        <>
          Client Secret 保存后不再显示；编辑时留空表示保持原凭据。
          {channel?.runtime?.status === "MISCONFIGURED"
            ? " 当前凭据不可用，请填写新 Secret 保存，再执行配置测试。"
            : ""}
        </>
      }
      asSheet={Boolean(channel)}
      wide
      pending={pending || createEnterprise.isPending}
      onClose={onCancel}
    >
      <form onSubmit={submit} className="grid gap-5">
        <div
          className={cn(
            "grid items-start gap-4",
            !channel && "sm:grid-cols-2 sm:[&>[role=alert]]:col-span-2"
          )}
        >
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
                setInitialForm({
                  ...initialForm,
                  client_id: event.target.value,
                })
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
                    {enterprise.name} ·{" "}
                    {enterpriseStatusLabel(enterprise.status)}
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
              对应钉钉官方 MCP 的
              ROBOT_CODE，用于企业机器人个人/群消息；不是工作通知 Agent
              ID，也不是 Secret。
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
          <EditorField
            label="外部操作确认卡片模板 ID"
            htmlFor="dingtalk-external-action-confirmation-card-template-id"
          >
            <Input
              id="dingtalk-external-action-confirmation-card-template-id"
              maxLength={256}
              value={form.external_action_confirmation_card_template_id}
              placeholder="例如：xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.schema"
              onChange={(event) =>
                setInitialForm({
                  ...initialForm,
                  external_action_confirmation_card_template_id:
                    event.target.value,
                })
              }
            />
            <p className="text-xs leading-5 text-muted-foreground">
              用于待办、日程、AI 表格等外部写入的逐次确认。模板必须发布在当前
              Client ID
              对应的钉钉应用中，并兼容平台固定的确认卡字段与回调合同；修改后仅影响新发起的操作。
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
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="submit"
            disabled={pending || createEnterprise.isPending}
          >
            {pending ? (
              <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
            ) : null}
            {channel ? "保存修改" : "创建渠道"}
          </Button>
          <FormDialogCancel disabled={pending || createEnterprise.isPending} />
        </div>
      </form>
    </FormDialog>
  )
}

function WebhookEditor({
  onOpenChange,
  onCreated,
}: {
  onOpenChange: (open: boolean) => void
  onCreated: (code: string) => void
}) {
  const create = useCreateWebhookChannel()
  const [form, setForm] = useState<WebhookChannelInput>({
    code: "",
    name: "",
    trigger_type: "generic",
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(form, {
      onSuccess: () => {
        onOpenChange(false)
        onCreated(form.code)
      },
    })
  }
  return (
    <FormDialog
      title="新建受管 Webhook"
      description="系统自动创建独立接收入口。创建后配置认证和消息映射，校验并发布后再启用。"
      pending={create.isPending}
      onClose={() => onOpenChange(false)}
    >
      <form onSubmit={submit} className="grid gap-5">
        <div className="space-y-4">
          <EditorField label="Webhook 编码" htmlFor="webhook-code">
            <Input
              id="webhook-code"
              required
              pattern={"[a-z][a-z0-9\\-]{2,63}"}
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
          <MutationError error={create.error} />
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="submit" disabled={create.isPending}>
            创建并配置 Webhook
          </Button>
          <FormDialogCancel disabled={create.isPending} />
        </div>
      </form>
    </FormDialog>
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
    external_action_confirmation_card_template_id:
      channel?.external_action_confirmation_card_template_id ?? "",
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
