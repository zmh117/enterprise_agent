import { CircleDotIcon, FlaskConicalIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { prototypeMeta } from "@/mocks/dashboard"

export function PlatformHeader() {
  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/85 lg:px-6">
      <div className="flex w-full min-w-0 items-center gap-3">
        <SidebarTrigger className="-ml-1" aria-label="展开或收起导航" />
        <Separator orientation="vertical" className="h-5" />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">产品结构评审</p>
          <p className="hidden truncate text-xs text-muted-foreground sm:block">
            业务应用控制面 · 静态展示
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
            {prototypeMeta.environment}
          </Badge>
          <Badge className="gap-1.5 bg-indigo-600 text-white hover:bg-indigo-600">
            <FlaskConicalIcon aria-hidden="true" />
            {prototypeMeta.label}
          </Badge>
        </div>
      </div>
    </header>
  )
}
