import type { ReactNode } from "react"
import { LoaderCircleIcon, ShieldXIcon } from "lucide-react"
import { Link } from "react-router-dom"

import { buttonVariants } from "@/components/ui/button"
import { useAdminCapabilitySummary } from "@/contexts/auth/application/admin-capability-query"

export function CapabilityGate({
  capability,
  children,
}: {
  capability: string
  children: ReactNode
}) {
  const query = useAdminCapabilitySummary()
  if (query.isLoading) {
    return (
      <div className="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
        <LoaderCircleIcon className="size-4 animate-spin" aria-hidden="true" />
        正在校验页面权限…
      </div>
    )
  }
  if (query.isError || !query.data?.capabilities.includes(capability)) {
    return (
      <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center gap-4 px-6 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <ShieldXIcon aria-hidden="true" />
        </span>
        <div>
          <h1 className="text-xl font-semibold">无权访问此页面</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            当前账号未获得该管理功能权限，请联系平台管理员调整角色。
          </p>
        </div>
        <Link to="/" className={buttonVariants()}>
          返回工作台
        </Link>
      </div>
    )
  }
  return children
}
