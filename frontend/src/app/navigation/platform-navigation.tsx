import { useState } from "react"
import {
  BoxesIcon,
  ChevronsUpDownIcon,
  LoaderCircleIcon,
  LogOutIcon,
} from "lucide-react"
import { Link, useLocation } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
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
import { useAdminCapabilitySummary } from "@/contexts/auth/application/admin-capability-query"
import {
  useAuthenticatedUser,
  useLogout,
} from "@/contexts/auth/presentation/authenticated-user-state"
import { ApiError } from "@/shared/api/api-client"

export function PlatformNavigation() {
  const location = useLocation()
  const authenticatedUser = useAuthenticatedUser()
  const logout = useLogout()
  const capabilityQuery = useAdminCapabilitySummary()
  const capabilitySet = new Set(capabilityQuery.data?.capabilities ?? [])
  const canReadCandidates = capabilitySet.has("identity.discovery.read")
  const candidateCount = useDingTalkIdentityCandidateCount(canReadCandidates)
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
        {navigationGroups.map((group) => {
          const visibleItems = group.items.filter(
            (item) =>
              !item.requiredCapability ||
              capabilitySet.has(item.requiredCapability)
          )
          if (visibleItems.length === 0) return null
          return (
            <SidebarGroup key={group.label} className="py-1">
              <SidebarGroupLabel className="text-[11px] font-medium tracking-wide text-muted-foreground/80">
                {group.label}
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {visibleItems.map((item) => {
                    const Icon = item.icon
                    const activeHref = resolveActiveNavigationHref(
                      location.pathname,
                      visibleItems
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
                          render={
                            item.href ? <Link to={item.href} /> : undefined
                          }
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
          )
        })}
      </SidebarContent>

      <SidebarSeparator />
      <SidebarFooter className="p-3">
        <AccountMenu user={authenticatedUser} logout={logout} />
      </SidebarFooter>
    </Sidebar>
  )
}

function AccountMenu({
  user,
  logout,
}: {
  user: ReturnType<typeof useAuthenticatedUser>
  logout: () => Promise<void>
}) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState("")
  const displayName = user.display_name.trim() || user.username
  const initials = Array.from(displayName).slice(0, 2).join("").toUpperCase()

  const openConfirmation = () => {
    setErrorMessage("")
    setConfirmOpen(true)
  }

  const confirmLogout = async () => {
    setSubmitting(true)
    setErrorMessage("")
    try {
      await logout()
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : "退出失败，请稍后重试。"
      )
      setSubmitting(false)
    }
  }

  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <SidebarMenuButton
                  size="lg"
                  className="h-auto rounded-lg border bg-background/70 px-2.5 py-2 shadow-xs"
                  aria-label={`打开 ${displayName} 的账户菜单`}
                >
                  <Avatar className="rounded-lg" aria-hidden="true">
                    <AvatarFallback className="rounded-lg bg-indigo-100 font-medium text-indigo-700">
                      {initials}
                    </AvatarFallback>
                  </Avatar>
                  <span className="grid min-w-0 flex-1 text-left text-sm leading-tight">
                    <span className="truncate font-medium">{displayName}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      @{user.username}
                    </span>
                  </span>
                  <ChevronsUpDownIcon
                    className="ml-auto size-4 text-muted-foreground"
                    aria-hidden="true"
                  />
                </SidebarMenuButton>
              }
            />
            <DropdownMenuContent
              className="w-56"
              side="top"
              align="start"
              sideOffset={8}
            >
              <DropdownMenuGroup>
                <DropdownMenuLabel className="px-2 py-1.5">
                  当前账户
                </DropdownMenuLabel>
                <div className="px-2 pb-1.5 text-xs text-muted-foreground">
                  {user.auth_source === "local" ? "系统账号" : user.auth_source}
                </div>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onClick={openConfirmation}
              >
                <LogOutIcon aria-hidden="true" />
                退出账户
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>

      <AlertDialog
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!submitting) {
            setConfirmOpen(open)
            if (!open) setErrorMessage("")
          }
        }}
      >
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>退出当前账户？</AlertDialogTitle>
            <AlertDialogDescription>
              退出后需要重新登录，才能继续访问管理控制面。
            </AlertDialogDescription>
          </AlertDialogHeader>
          {errorMessage ? (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage}
            </p>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>取消</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={submitting}
              onClick={() => void confirmLogout()}
            >
              {submitting ? (
                <LoaderCircleIcon className="animate-spin" aria-hidden="true" />
              ) : (
                <LogOutIcon aria-hidden="true" />
              )}
              {submitting ? "正在退出…" : "确认退出"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
