import { CircleDotIcon, ShieldCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
export function PlatformHeader() {
  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/85 lg:px-6">
      <div className="flex w-full min-w-0 items-center gap-3">
        <SidebarTrigger className="-ml-1" aria-label="展开或收起导航" />
        <Separator orientation="vertical" className="h-5" />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">管理控制面</p>
          <p className="hidden truncate text-xs text-muted-foreground sm:block">
            业务应用 · Agent 配置 · 用户与外部身份
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Badge
            variant="outline"
            className="hidden gap-1.5 font-normal sm:inline-flex"
          >
            <CircleDotIcon
              className="size-3 fill-emerald-500 text-emerald-500"
              aria-hidden="true"
            />
            已连接后端
          </Badge>
          <Badge className="gap-1.5 bg-indigo-600 text-white hover:bg-indigo-600">
            <ShieldCheckIcon aria-hidden="true" />
            受保护会话
          </Badge>
        </div>
      </div>
    </header>
  )
}
