import { BoxesIcon, CircleDotDashedIcon } from "lucide-react"

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

export function PlatformNavigation() {
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
                  Control Plane Prototype
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
                  return (
                    <SidebarMenuItem key={item.label}>
                      <SidebarMenuButton
                        isActive={item.active}
                        disabled={!item.active}
                        title={
                          item.active ? item.label : `${item.label} · 规划中`
                        }
                        aria-label={
                          item.active ? item.label : `${item.label}，规划中`
                        }
                        className="disabled:pointer-events-auto disabled:cursor-not-allowed disabled:opacity-75"
                      >
                        <Icon aria-hidden="true" />
                        <span>{item.label}</span>
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
            <CircleDotDashedIcon
              className="size-3.5 text-amber-600"
              aria-hidden="true"
            />
            界面原型
          </div>
          <p className="mt-1.5 leading-5">无登录、无真实数据、无业务操作</p>
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
