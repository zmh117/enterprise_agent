import { BoxesIcon, CircleCheckBigIcon } from "lucide-react"
import { Link, useLocation } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from "@/components/ui/sidebar"
import { navigationGroups } from "@/mocks/dashboard"
import { resolveActiveNavigationHref } from "@/app/navigation/navigation-match"
import { useDingTalkIdentityCandidateCount } from "@/contexts/dingtalk-identity-discovery"

export function PlatformNavigation() {
  const location = useLocation()
  const candidateCount = useDingTalkIdentityCandidateCount()
  return (
    <Sidebar collapsible="offcanvas" variant="sidebar">
      <SidebarHeader className="h-16 justify-center border-b px-3">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              className="h-10 cursor-default gap-3 px-2 hover:bg-transparent"
              aria-label="Agent 应用平台"
            >
              <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
                <BoxesIcon className="size-4" aria-hidden="true" />
              </span>
              <span className="flex flex-col text-left leading-tight">
                <span className="font-semibold">Agent 应用平台</span>
                <span className="text-[11px] text-muted-foreground">
                  Control Plane
                </span>
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="py-2">
        {navigationGroups.map((group) => (
          <SidebarGroup key={group.label} className="py-1">
            <SidebarGroupLabel className="text-[11px] font-medium tracking-wide text-muted-foreground/80">
              {group.label}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const Icon = item.icon
                  const activeHref = resolveActiveNavigationHref(
                    location.pathname,
                    group.items
                  )
                  return (
                    <SidebarMenuItem key={item.label}>
                      <SidebarMenuButton
                        isActive={
                          Boolean(item.href) && item.href === activeHref
                        }
                        disabled={!item.active}
                        title={
                          item.active ? item.label : `${item.label} · 规划中`
                        }
                        aria-label={
                          item.active ? item.label : `${item.label}，规划中`
                        }
                        className="disabled:pointer-events-auto disabled:cursor-not-allowed disabled:opacity-75"
                        render={item.href ? <Link to={item.href} /> : undefined}
                      >
                        <Icon aria-hidden="true" />
                        <span>{item.label}</span>
                        {item.badge === "dingtalk_identity_candidates" &&
                        candidateCount.data ? (
                          <Badge
                            variant="secondary"
                            className="ml-auto h-5 min-w-5 px-1.5 text-[10px]"
                            aria-label={`${candidateCount.data} 个未绑定钉钉用户`}
                          >
                            {candidateCount.data > 99
                              ? "99+"
                              : candidateCount.data}
                          </Badge>
                        ) : null}
                        {!item.active ? (
                          <Badge
                            variant="outline"
                            className="ml-auto h-4 px-1.5 text-[9px] font-normal text-muted-foreground"
                          >
                            规划中
                          </Badge>
                        ) : null}
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarSeparator />
      <SidebarFooter className="p-3">
        <div className="rounded-lg border bg-background/70 p-3 text-xs text-muted-foreground">
          <div className="flex items-center gap-2 font-medium text-foreground">
            <CircleCheckBigIcon
              className="size-3.5 text-emerald-600"
              aria-hidden="true"
            />
            MVP 已接线
          </div>
          <p className="mt-1.5 leading-5">
            当前开放业务应用、Agent 配置、用户与外部身份
          </p>
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
