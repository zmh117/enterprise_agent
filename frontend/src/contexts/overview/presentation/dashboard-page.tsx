import { ArrowRightIcon } from "lucide-react"
import { Link } from "react-router-dom"
import { navigationGroups } from "@/mocks/dashboard"
import { useAdminCapabilitySummary } from "@/contexts/auth/application/admin-capability-query"
import { useDingTalkIdentityCandidateCount } from "@/contexts/dingtalk-identity-discovery/application/dingtalk-identity-candidate-queries"
import { ListPage } from "@/shared/presentation/list-page"

const shortcuts = [
  "/applications",
  "/agent-profiles",
  "/operations/jobs",
  "/users",
  "/platform/resources",
  "/me/external-identities",
]
const items = navigationGroups.flatMap((group) => group.items)

export function DashboardPage() {
  const capabilities = useAdminCapabilitySummary()
  const allowed = new Set(capabilities.data?.capabilities)
  const canReadCandidates = allowed.has("identity.discovery.read")
  const candidates = useDingTalkIdentityCandidateCount(canReadCandidates)
  return (
    <ListPage title="工作台">
      <section
        aria-label="常用入口"
        className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"
      >
        {shortcuts.map((path) => {
          const item = items.find((item) => item.href === path)
          if (
            !item ||
            (item.requiredCapability && !allowed.has(item.requiredCapability))
          )
            return null
          return (
            <Link
              key={path}
              to={path}
              className="group flex items-center gap-3 rounded-xl border bg-card px-4 py-5 hover:border-primary/40 focus-visible:outline-ring"
            >
              <item.icon className="size-5 text-muted-foreground" />
              <span className="font-medium">{item.label}</span>
              <ArrowRightIcon className="ml-auto size-4 text-muted-foreground group-hover:text-foreground" />
            </Link>
          )
        })}
      </section>
      {canReadCandidates && (
        <section className="space-y-3" aria-labelledby="pending-heading">
          <h2 id="pending-heading" className="text-base font-semibold">
            待处理
          </h2>
          <Link
            to="/users/dingtalk-discovery"
            className="flex items-center gap-3 rounded-xl border bg-card px-4 py-3 text-sm hover:border-primary/40"
          >
            未绑定钉钉用户
            <span className="ml-auto tabular-nums">
              {candidates.isError
                ? "计数暂不可用"
                : candidates.data === undefined
                  ? "加载中…"
                  : `${candidates.data} 人`}
            </span>
            <ArrowRightIcon className="size-4 text-muted-foreground" />
          </Link>
        </section>
      )}
    </ListPage>
  )
}
