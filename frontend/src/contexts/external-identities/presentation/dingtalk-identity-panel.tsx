import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  useExternalIdentities,
  useSelfExternalIdentities,
  useUnbindIdentity,
  useUpdateIdentityStatus,
} from "@/contexts/external-identities/application/external-identity-queries"
import type { AdminDingTalkIdentity } from "@/contexts/external-identities/domain/external-identity"

type Props =
  | { mode: "self" }
  | { mode: "admin"; userId: string; canManage?: boolean }

export function ExternalIdentityPanel(props: Props) {
  if (props.mode === "self") return <SelfDingTalkIdentities />
  return (
    <AdminDingTalkIdentities
      userId={props.userId}
      canManage={Boolean(props.canManage)}
    />
  )
}

function SelfDingTalkIdentities() {
  const query = useSelfExternalIdentities()
  if (query.isPending) return <Notice text="正在加载钉钉身份…" />
  if (query.isError) return <Notice text="钉钉身份加载失败，请稍后重试。" />
  const identities = query.data?.dingtalk ?? []
  return (
    <div className="space-y-3">
      {identities.map((identity) => (
        <Card key={`${identity.enterprise?.corp_id}:${identity.staff_id}`}>
          <CardHeader>
            <CardTitle className="text-base">{identity.nickname || identity.staff_id}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm text-muted-foreground">
            <p>企业：{identity.enterprise?.name || "未记录"}</p>
            <p className="font-mono text-xs">Staff ID：{identity.staff_id}</p>
            <p>状态：{identity.status === "enabled" ? "已启用" : "已停用"}</p>
          </CardContent>
        </Card>
      ))}
      {identities.length === 0 ? <Notice text="当前没有已绑定的钉钉身份。" /> : null}
    </div>
  )
}

function AdminDingTalkIdentities({
  userId,
  canManage,
}: {
  userId: string
  canManage: boolean
}) {
  const query = useExternalIdentities(userId)
  const update = useUpdateIdentityStatus(userId)
  const unbind = useUnbindIdentity(userId)
  if (query.isPending) return <Notice text="正在加载外部身份…" />
  if (query.isError) return <Notice text="外部身份加载失败，请稍后重试。" />
  const current = query.data?.current ?? []
  const history = query.data?.history ?? []
  return (
    <div className="space-y-4">
      <IdentityList
        title="当前钉钉身份"
        identities={current}
        canManage={canManage}
        onToggle={(identity) =>
          update.mutate({
            identityId: identity.identity_id,
            expectedRevision: identity.revision,
            status: identity.status === "enabled" ? "disabled" : "enabled",
          })
        }
        onUnbind={(identity) =>
          unbind.mutate({
            identityId: identity.identity_id,
            expectedRevision: identity.revision,
          })
        }
      />
      <IdentityList title="历史钉钉身份" identities={history} canManage={false} />
      {current.length === 0 && history.length === 0 ? (
        <Notice text="该用户当前没有钉钉身份记录。" />
      ) : null}
    </div>
  )
}

function IdentityList({
  title,
  identities,
  canManage,
  onToggle,
  onUnbind,
}: {
  title: string
  identities: AdminDingTalkIdentity[]
  canManage: boolean
  onToggle?: (identity: AdminDingTalkIdentity) => void
  onUnbind?: (identity: AdminDingTalkIdentity) => void
}) {
  if (identities.length === 0) return null
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">{title}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {identities.map((identity) => (
          <div key={identity.identity_id} className="flex items-start justify-between gap-3 rounded-md border p-3">
            <div className="space-y-1 text-sm">
              <p className="font-medium">{identity.nickname || identity.staff_id}</p>
              <p className="text-muted-foreground">{identity.enterprise?.name || "未记录企业"}</p>
              <p className="font-mono text-xs text-muted-foreground">{identity.staff_id}</p>
            </div>
            {canManage && identity.status !== "unbound" ? (
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => onToggle?.(identity)}>
                  {identity.status === "enabled" ? "停用" : "启用"}
                </Button>
                <Button variant="destructive" size="sm" onClick={() => onUnbind?.(identity)}>
                  解绑
                </Button>
              </div>
            ) : null}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function Notice({ text }: { text: string }) {
  return <div className="rounded-md border border-dashed p-5 text-sm text-muted-foreground">{text}</div>
}
