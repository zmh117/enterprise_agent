import { useLocation } from "react-router-dom"
import { resolveActiveNavigationHref } from "@/app/navigation/navigation-match"
import { navigationGroups } from "@/mocks/dashboard"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"

export function PlatformHeader() {
  const { pathname } = useLocation()
  const group = navigationGroups.find((group) =>
    resolveActiveNavigationHref(pathname, group.items)
  )
  const section = pathname.startsWith("/operations/")
    ? "运行中心"
    : group?.label
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4 text-sm text-muted-foreground lg:px-6">
      <SidebarTrigger className="-ml-1" aria-label="展开或收起导航" />
      <Separator orientation="vertical" className="my-auto h-4" />
      <span>管理控制面</span>
      {section && (
        <>
          <span aria-hidden="true">/</span>
          <span className="text-foreground">{section}</span>
        </>
      )}
    </header>
  )
}
