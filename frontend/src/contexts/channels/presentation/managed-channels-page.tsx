import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  CableIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  RotateCwIcon,
  ShieldCheckIcon,
  SquareIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  createDingTalkEnterprise,
  listChannelCredentials,
  listDingTalkEnterprises,
  listManagedChannels,
  restartManagedChannel,
  saveDingTalkChannel,
  setManagedChannelEnabled,
  testManagedChannel,
  type ManagedChannel,
} from "@/contexts/channels/infrastructure/managed-channel-api"
import { useAuthenticatedUser } from "@/contexts/auth/presentation/authenticated-user-state"
import {
  ManagementError,
  ManagementLoading,
  ManagementPage,
  MutationNotice,
} from "@/shared/presentation/management-states"
import { SectionHeading } from "@/shared/presentation/section-heading"

const channelKey = ["admin", "managed-channels"] as const

export function ManagedChannelsPage() {
  const user = useAuthenticatedUser()
  const query = useQuery({ queryKey: channelKey, queryFn: listManagedChannels })
  const client = useQueryClient()
  const [result, setResult] = useState("")
  const [creating, setCreating] = useState(false)
  const [creatingEnterprise, setCreatingEnterprise] = useState(false)
  const [editing, setEditing] = useState<ManagedChannel | null>(null)
  const enterprises = useQuery({
    queryKey: ["admin", "managed-channels", "enterprises"],
    queryFn: listDingTalkEnterprises,
    enabled: Boolean(user.capabilities.channels_manage),
  })
  const credentials = useQuery({
    queryKey: ["admin", "managed-channels", "credentials"],
    queryFn: listChannelCredentials,
    enabled: Boolean(user.capabilities.channels_manage),
  })
  const statusMutation = useMutation({
    mutationFn: (input: { channel: ManagedChannel; enabled: boolean }) =>
      setManagedChannelEnabled(input.channel, input.enabled),
    onSuccess: async () => client.invalidateQueries({ queryKey: channelKey }),
  })
  const restartMutation = useMutation({
    mutationFn: restartManagedChannel,
    onSuccess: async () => client.invalidateQueries({ queryKey: channelKey }),
  })
  const testMutation = useMutation({
    mutationFn: testManagedChannel,
    onSuccess: (response) => setResult(response.result.summary),
  })
  const error = statusMutation.error || restartMutation.error || testMutation.error
  return (
    <ManagementPage>
      <SectionHeading
        eyebrow="Channel Governance"
        title="渠道与触发器"
        description="查看钉钉应用和 Webhook 的企业归属、入口方向、运行状态与安全错误；启停不会改写 Application Publication。"
        action={<div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" disabled={query.isFetching} onClick={() => void query.refetch()}><RefreshCwIcon className={query.isFetching ? "animate-spin" : ""} />刷新</Button>
          {user.capabilities.channels_manage ? <Button type="button" variant="outline" onClick={() => setCreatingEnterprise((value) => !value)}><PlusIcon />钉钉企业</Button> : null}
          {user.capabilities.channels_manage ? <Button type="button" onClick={() => { setCreating((value) => !value); setEditing(null) }}><PlusIcon />钉钉应用</Button> : null}
        </div>}
      />
      {creatingEnterprise ? <EnterpriseForm onDone={async () => { setCreatingEnterprise(false); await enterprises.refetch() }} /> : null}
      {creating ? <ChannelEditor enterprises={enterprises.data ?? []} credentials={credentials.data ?? []} onDone={async () => { setCreating(false); await client.invalidateQueries({ queryKey: channelKey }) }} /> : null}
      {editing ? <ChannelEditor channel={editing} enterprises={enterprises.data ?? []} credentials={credentials.data ?? []} onDone={async () => { setEditing(null); await client.invalidateQueries({ queryKey: channelKey }) }} onCancel={() => setEditing(null)} /> : null}
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error} retry={() => void query.refetch()} />
      <ManagementError error={enterprises.error || credentials.error} retry={() => { void enterprises.refetch(); void credentials.refetch() }} />
      <MutationNotice error={error} />
      {result ? <p role="status" className="rounded-lg border bg-muted/30 p-3 text-sm">最近测试：{result}</p> : null}
      <div className="space-y-3">
        {query.data?.map((channel) => (
          <Card key={channel.id} className="shadow-none">
            <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <CableIcon className="size-4" />
                  <p className="font-medium">{channel.name}</p>
                  <Badge variant="outline">{channel.kind === "DINGTALK_APP_ROBOT" ? "钉钉应用" : "Webhook"}</Badge>
                  <Badge variant={channel.enabled ? "secondary" : "outline"}>{channel.enabled ? "启用" : "停用"}</Badge>
                  <Badge variant="outline">Runtime {runtimeLabel(channel.runtime?.status || "STOPPED")}</Badge>
                </div>
                <p className="mt-1 font-mono text-xs text-muted-foreground">{channel.id} · r{channel.revision}</p>
                {channel.enterprise ? (
                  <p className="mt-1 text-xs text-muted-foreground">企业：{channel.enterprise.name} · {channel.enterprise.status}</p>
                ) : null}
                {channel.runtime?.last_error ? (
                  <p className="mt-2 text-sm text-destructive">{channel.runtime.last_error}</p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                {user.capabilities.channels_manage && channel.kind === "DINGTALK_APP_ROBOT" ? (
                  <Button type="button" variant="outline" onClick={() => { setEditing(channel); setCreating(false) }}><PencilIcon />编辑</Button>
                ) : null}
                {user.capabilities.channels_test ? (
                  <Button type="button" variant="outline" disabled={testMutation.isPending} onClick={() => testMutation.mutate(channel)}>
                    <ShieldCheckIcon />测试
                  </Button>
                ) : null}
                {user.capabilities.channels_manage && channel.kind === "DINGTALK_APP_ROBOT" && channel.enabled ? (
                  <Button type="button" variant="outline" disabled={restartMutation.isPending} onClick={() => restartMutation.mutate(channel)}>
                    <RotateCwIcon />重启
                  </Button>
                ) : null}
                {user.capabilities.channels_manage ? (
                  <Button type="button" variant={channel.enabled ? "outline" : "default"} disabled={statusMutation.isPending} onClick={() => statusMutation.mutate({ channel, enabled: !channel.enabled })}>
                    {channel.enabled ? <SquareIcon /> : null}{channel.enabled ? "停用" : "启用"}
                  </Button>
                ) : null}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </ManagementPage>
  )
}

function EnterpriseForm({ onDone }: { onDone: () => Promise<unknown> }) {
  const mutation = useMutation({ mutationFn: createDingTalkEnterprise, onSuccess: onDone })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    mutation.mutate(String(data.get("name") || ""))
  }
  return <Card className="max-w-2xl shadow-none"><CardContent className="p-5"><form className="flex flex-wrap items-end gap-3" onSubmit={submit}><div className="min-w-64 flex-1 space-y-2"><Label htmlFor="enterprise-name">钉钉企业名称</Label><Input id="enterprise-name" name="name" required maxLength={120} /></div><Button type="submit" disabled={mutation.isPending}>创建待验证企业</Button><div className="w-full"><MutationNotice error={mutation.error} /></div></form></CardContent></Card>
}

function ChannelEditor({
  channel,
  enterprises,
  credentials,
  onDone,
  onCancel,
}: {
  channel?: ManagedChannel
  enterprises: Awaited<ReturnType<typeof listDingTalkEnterprises>>
  credentials: Awaited<ReturnType<typeof listChannelCredentials>>
  onDone: () => Promise<unknown>
  onCancel?: () => void
}) {
  const mutation = useMutation({ mutationFn: saveDingTalkChannel, onSuccess: onDone })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    mutation.mutate({
      channelId: channel?.id,
      form: {
        expected_revision: channel?.revision ?? 0,
        name: String(data.get("name") || ""),
        client_id: String(data.get("client_id") || ""),
        credential_id: String(data.get("credential_id") || ""),
        dingtalk_enterprise_id: String(data.get("dingtalk_enterprise_id") || ""),
        allow_private_chat: data.get("allow_private_chat") === "on",
        allow_group_chat: data.get("allow_group_chat") === "on",
        require_group_at: data.get("require_group_at") === "on",
        enabled: channel?.enabled ?? false,
      },
    })
  }
  return <Card className="shadow-none"><CardContent className="p-5"><form className="grid gap-4 md:grid-cols-2" onSubmit={submit}>
    <div className="space-y-2"><Label htmlFor="channel-name">名称</Label><Input id="channel-name" name="name" defaultValue={channel?.name || ""} required /></div>
    <div className="space-y-2"><Label htmlFor="channel-client-id">钉钉 Client ID</Label><Input id="channel-client-id" name="client_id" defaultValue={channel?.client_id || ""} required /></div>
    <div className="space-y-2"><Label htmlFor="channel-enterprise">钉钉企业</Label><select id="channel-enterprise" name="dingtalk_enterprise_id" defaultValue={channel?.enterprise?.id || ""} required className="h-9 w-full rounded-md border bg-background px-3 text-sm"><option value="">请选择企业</option>{enterprises.filter((item) => !["DISABLED", "ARCHIVED"].includes(item.status)).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status}</option>)}</select></div>
    <div className="space-y-2"><Label htmlFor="channel-credential">Credential</Label><select id="channel-credential" name="credential_id" required={!channel} className="h-9 w-full rounded-md border bg-background px-3 text-sm"><option value="">{channel ? "保留当前 Credential" : "请选择 Credential"}</option>{credentials.map((item) => <option key={item.id} value={item.id}>{item.code} · {item.purpose || "未标注用途"} · {item.masked_summary}</option>)}</select><p className="text-xs text-muted-foreground">只提交 Credential ID；Client Secret 不进入页面状态或 Connector DTO。</p></div>
    <label className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" name="allow_private_chat" defaultChecked={channel?.capabilities?.private_chat ?? true} />允许单聊</label>
    <label className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" name="allow_group_chat" defaultChecked={channel?.capabilities?.group_chat ?? true} />允许群聊</label>
    <label className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" name="require_group_at" defaultChecked={channel?.capabilities?.require_group_at ?? true} />群聊必须 @</label>
    <div className="md:col-span-2"><MutationNotice error={mutation.error} /></div>
    <div className="flex gap-2 md:col-span-2"><Button type="submit" disabled={mutation.isPending || !enterprises.length || !credentials.length}>{channel ? "保存配置" : "新建并保持停用"}</Button>{onCancel ? <Button type="button" variant="outline" onClick={onCancel}>取消</Button> : null}</div>
  </form></CardContent></Card>
}

function runtimeLabel(value: string) {
  const labels: Record<string, string> = {
    CONNECTED: "已连接",
    REGISTERED: "已注册",
    READY: "就绪",
    STOPPED: "已停止",
    STALE: "心跳过期",
    STARTING: "启动中",
    RECONNECTING: "重连中",
    AUTH_FAILED: "认证失败",
    ERROR: "异常",
  }
  return labels[value] || value
}
