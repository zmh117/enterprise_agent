import {
  AppWindowIcon,
  BotIcon,
  CableIcon,
  DatabaseIcon,
  KeyRoundIcon,
  ServerIcon,
  ShieldCheckIcon,
  UsersIcon,
} from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuthenticatedUser } from "@/contexts/auth/presentation/authenticated-user-state"
import { getGovernanceDashboard } from "@/contexts/overview/infrastructure/governance-dashboard-api"
import { ManagementError, ManagementLoading, ManagementPage } from "@/shared/presentation/management-states"
import { SectionHeading } from "@/shared/presentation/section-heading"

const entries = [
  { code: "agents", title: "Agent", description: "Draft、校验、Publication 与历史", href: "/agent-profiles", capability: "agents_read", icon: BotIcon },
  { code: "applications", title: "Application", description: "发布、环境激活与停用", href: "/applications", capability: "applications_read", icon: AppWindowIcon },
  { code: "channels", title: "渠道", description: "钉钉与 Webhook 运行治理", href: "/applications/channels", capability: "channels_read", icon: CableIcon },
  { code: "users", title: "人员与账号", description: "用户、角色与统一身份", href: "/users", capability: "users_read", icon: UsersIcon },
  { code: "mcp_servers", title: "MCP Server", description: "受信注册表与健康状态", href: "/mcp/servers", capability: "mcp_servers_read", icon: ServerIcon },
  { code: "mcp_tools", title: "Tool Publication", description: "服务端目录、发布与精确资源绑定", href: "/mcp/tools", capability: "mcp_tools_read", icon: ShieldCheckIcon },
  { code: "mcp_resources", title: "Resource", description: "Database、Redis、Loki", href: "/mcp/resources", capability: "mcp_resources_read", icon: DatabaseIcon },
  { code: "credentials", title: "Credential", description: "加密保存、轮换与依赖保护", href: "/mcp/credentials", capability: "secrets_read", icon: KeyRoundIcon },
]

export function GovernanceDashboardPage() {
  const user = useAuthenticatedUser()
  const visible = entries.filter((entry) => user.capabilities[entry.capability])
  const query = useQuery({ queryKey: ["admin", "dashboard"], queryFn: getGovernanceDashboard })
  const counts = new Map(query.data?.modules.map((item) => [item.code, item.count]) ?? [])
  return (
    <ManagementPage>
      <SectionHeading
        eyebrow="Governance Console"
        title="治理总览"
        description="聚合值来自当前会话权限范围内的真实控制面；无权对象不参与计数，也不使用静态 fixture 或伪造健康数据。"
      />
      {query.isLoading ? <ManagementLoading /> : null}
      <ManagementError error={query.error} retry={() => void query.refetch()} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {visible.map((entry) => {
          const Icon = entry.icon
          return (
            <Card key={entry.href} className="shadow-none transition-colors hover:border-primary/40">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base"><Icon className="size-4" />{entry.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-semibold tabular-nums">{counts.get(entry.code) ?? "—"}</p>
                <p className="min-h-10 text-sm text-muted-foreground">{entry.description}</p>
                <Link className="mt-4 inline-block text-sm font-medium text-primary hover:underline" to={entry.href}>进入治理 →</Link>
              </CardContent>
            </Card>
          )
        })}
      </div>
      {query.data ? <Card className="shadow-none"><CardHeader><CardTitle>当前 MCP 数据链路</CardTitle></CardHeader><CardContent><ol className="flex flex-col gap-2 text-sm lg:flex-row lg:items-center">{query.data.data_chain.map((item, index) => <li key={item} className="flex items-center gap-2"><span className="rounded-md border bg-muted/30 px-3 py-2">{item}</span>{index < query.data.data_chain.length - 1 ? <span className="text-muted-foreground" aria-hidden="true">→</span> : null}</li>)}</ol><p className="mt-3 text-xs text-muted-foreground">统计时间：{new Date(query.data.captured_at).toLocaleString("zh-CN")}</p></CardContent></Card> : null}
    </ManagementPage>
  )
}
