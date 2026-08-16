import { type ReactNode, useEffect } from "react"
import {
  CircleAlertIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  ShieldXIcon,
} from "lucide-react"
import { Link } from "react-router-dom"

import { Button, buttonVariants } from "@/components/ui/button"
import { useAdminCapabilitySummary } from "@/contexts/auth/application/admin-capability-query"
import { notifyAuthenticationRequired } from "@/contexts/auth/application/auth-session-events"
import { ApiError } from "@/shared/api/api-client"

export function CapabilityGate({
  capability,
  children,
}: {
  capability: string
  children: ReactNode
}) {
  const query = useAdminCapabilitySummary()
  const authenticationExpired =
    query.error instanceof ApiError && query.error.status === 401

  useEffect(() => {
    if (authenticationExpired) notifyAuthenticationRequired()
  }, [authenticationExpired])

  if (query.isLoading) {
    return (
      <div className="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
        <LoaderCircleIcon className="size-4 animate-spin" aria-hidden="true" />
        正在校验页面权限…
      </div>
    )
  }
  if (authenticationExpired) {
    return (
      <CapabilityState
        title="登录状态已失效"
        description="正在重新确认管理会话，请稍候。"
        icon={<LoaderCircleIcon className="animate-spin" aria-hidden="true" />}
      />
    )
  }
  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 403) {
      return <UnauthorizedState />
    }
    return (
      <CapabilityState
        title="管理服务不可用"
        description="权限信息暂时无法加载，请重试；你的账号权限尚未被判定为拒绝。"
        icon={<CircleAlertIcon aria-hidden="true" />}
        action={
          <Button onClick={() => void query.refetch()}>
            <RefreshCwIcon aria-hidden="true" />
            重新校验
          </Button>
        }
      />
    )
  }
  if (!query.data?.capabilities.includes(capability)) {
    return <UnauthorizedState />
  }
  return children
}

function UnauthorizedState() {
  return (
    <CapabilityState
      title="无权访问此页面"
      description="当前账号未获得该管理功能权限，请联系平台管理员调整角色。"
      icon={<ShieldXIcon aria-hidden="true" />}
      destructive
      action={
        <Link to="/" className={buttonVariants()}>
          返回工作台
        </Link>
      }
    />
  )
}

function CapabilityState({
  title,
  description,
  icon,
  action,
  destructive = false,
}: {
  title: string
  description: string
  icon: ReactNode
  action?: ReactNode
  destructive?: boolean
}) {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center gap-4 px-6 text-center">
      <span
        className={
          destructive
            ? "flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive"
            : "flex size-12 items-center justify-center rounded-full bg-amber-100 text-amber-700"
        }
      >
        {icon}
      </span>
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  )
}
