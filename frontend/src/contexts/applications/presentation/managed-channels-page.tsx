import { CableIcon } from "lucide-react"

import { ManagedChannelsPanel } from "@/contexts/applications/presentation/managed-channels-panel"

export function ManagedChannelsPage() {
  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header>
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background text-indigo-600 shadow-sm">
            <CableIcon className="size-5" aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              渠道与触发器
            </h1>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              管理平台级入口 Channel。当前支持受管 Webhook 和钉钉应用机器人。
            </p>
          </div>
        </div>
      </header>

      <div className="rounded-lg border bg-muted/25 p-4 text-sm leading-6">
        <p className="font-medium">Channel 配置与业务应用草稿相互独立</p>
        <p className="mt-1 text-muted-foreground">
          Channel
          启用且满足入口条件后，才能在业务应用的“组成配置”中绑定为触发器；
          此页面不会直接修改任何业务应用、Agent Publication 或已激活版本。
        </p>
      </div>

      <ManagedChannelsPanel />
    </div>
  )
}
