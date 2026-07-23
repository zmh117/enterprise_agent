import type { ReactNode } from "react"

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { PlatformNavigation } from "@/app/navigation/platform-navigation"
import { PlatformHeader } from "@/app/shell/platform-header"

type PlatformShellProps = {
  children: ReactNode
}

export function PlatformShell({ children }: PlatformShellProps) {
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
        <main className="min-w-0 flex-1">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  )
}
