import { useState } from "react"
import {
  BoxesIcon,
  ChevronsUpDownIcon,
  HistoryIcon,
  KeyRoundIcon,
  Link2Icon,
  LoaderCircleIcon,
  LogOutIcon,
} from "lucide-react"
import { Link, useLocation } from "react-router-dom"

import { resolveActiveNavigationHref } from "@/app/navigation/navigation-match"
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
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
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
import {
  useAuthenticatedUser,
  useLogout,
} from "@/contexts/auth/presentation/authenticated-user-state"
import { ApiError } from "@/shared/api/api-client"

const navigation = [
  { label: "Job 与会话历史", href: "/operations/jobs", icon: HistoryIcon },
  { label: "我的外部身份", href: "/me/external-identities", icon: Link2Icon },
  { label: "密码与会话", href: "/account/security", icon: KeyRoundIcon },
]

export function PlatformNavigation() {
  const location = useLocation()
  const activeHref = resolveActiveNavigationHref(location.pathname, navigation)
  const user = useAuthenticatedUser()
  const logout = useLogout()
  return (
    <Sidebar collapsible="offcanvas" variant="sidebar">
      <SidebarHeader className="h-16 justify-center border-b px-3">
        <SidebarMenu><SidebarMenuItem><SidebarMenuButton className="h-10 cursor-default gap-3 px-2 hover:bg-transparent" aria-label="Agent 用户门户">
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground"><BoxesIcon className="size-4" /></span>
          <span className="flex flex-col text-left leading-tight"><span className="font-semibold">Agent 用户门户</span><span className="text-[11px] text-muted-foreground">History & Identity</span></span>
        </SidebarMenuButton></SidebarMenuItem></SidebarMenu>
      </SidebarHeader>
      <SidebarContent className="py-2">
        <SidebarGroup>
          <SidebarGroupLabel>本人视图</SidebarGroupLabel>
          <SidebarGroupContent><SidebarMenu>
            {navigation.map((item) => {
              const Icon = item.icon
              return <SidebarMenuItem key={item.href}><SidebarMenuButton isActive={activeHref === item.href} render={<Link to={item.href} />}><Icon /><span>{item.label}</span></SidebarMenuButton></SidebarMenuItem>
            })}
          </SidebarMenu></SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarSeparator />
      <SidebarFooter className="p-3"><AccountMenu user={user} logout={logout} /></SidebarFooter>
    </Sidebar>
  )
}

function AccountMenu({ user, logout }: { user: ReturnType<typeof useAuthenticatedUser>; logout: () => Promise<void> }) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState("")
  const displayName = user.display_name.trim() || user.username
  const initials = Array.from(displayName).slice(0, 2).join("").toUpperCase()
  const confirmLogout = async () => {
    setSubmitting(true)
    setErrorMessage("")
    try {
      await logout()
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.message : "退出失败，请稍后重试。")
      setSubmitting(false)
    }
  }
  return (
    <>
      <SidebarMenu><SidebarMenuItem><DropdownMenu>
        <DropdownMenuTrigger render={<SidebarMenuButton size="lg" className="h-auto rounded-lg border bg-background/70 px-2.5 py-2" aria-label={`打开 ${displayName} 的账户菜单`}>
          <Avatar className="rounded-lg"><AvatarFallback className="rounded-lg">{initials}</AvatarFallback></Avatar>
          <span className="grid min-w-0 flex-1 text-left text-sm leading-tight"><span className="truncate font-medium">{displayName}</span><span className="truncate text-xs text-muted-foreground">@{user.username}</span></span>
          <ChevronsUpDownIcon className="ml-auto size-4" />
        </SidebarMenuButton>} />
        <DropdownMenuContent className="w-56" side="top" align="start" sideOffset={8}>
          <DropdownMenuGroup><DropdownMenuLabel>当前账户</DropdownMenuLabel></DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem render={<Link to="/me/external-identities" />}><Link2Icon />我的外部身份</DropdownMenuItem>
          <DropdownMenuItem render={<Link to="/account/security" />}><KeyRoundIcon />密码与会话</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onClick={() => { setErrorMessage(""); setConfirmOpen(true) }}><LogOutIcon />退出账户</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu></SidebarMenuItem></SidebarMenu>
      <AlertDialog open={confirmOpen} onOpenChange={(open) => { if (!submitting) { setConfirmOpen(open); if (!open) setErrorMessage("") } }}>
        <AlertDialogContent size="sm"><AlertDialogHeader><AlertDialogTitle>退出当前账户？</AlertDialogTitle><AlertDialogDescription>退出后需要重新登录才能查看本人历史和身份。</AlertDialogDescription></AlertDialogHeader>
          {errorMessage ? <p role="alert" className="text-sm text-destructive">{errorMessage}</p> : null}
          <AlertDialogFooter><AlertDialogCancel disabled={submitting}>取消</AlertDialogCancel><AlertDialogAction variant="destructive" disabled={submitting} onClick={() => void confirmLogout()}>{submitting ? <LoaderCircleIcon className="animate-spin" /> : <LogOutIcon />}{submitting ? "正在退出…" : "确认退出"}</AlertDialogAction></AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
