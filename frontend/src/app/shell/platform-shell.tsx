import { Outlet } from "react-router-dom"

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { PlatformNavigation } from "@/app/navigation/platform-navigation"
import { PlatformHeader } from "@/app/shell/platform-header"

export function PlatformShell() {
  return (
    <SidebarProvider
      style={
        {
          "--sidebar-width": "16rem",
        } as React.CSSProperties
      }
    >
      <PlatformNavigation />
      <SidebarInset className="min-w-0 bg-muted/30">
        <PlatformHeader />
        <main className="min-w-0 flex-1">
          <Outlet />
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
