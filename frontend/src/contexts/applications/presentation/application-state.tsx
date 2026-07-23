import {
  AlertTriangleIcon,
  LockKeyholeIcon,
  LogInIcon,
  ServerOffIcon,
  ToggleLeftIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { ApiError } from "@/shared/api/api-client"

export function ApplicationState({
  error,
  retry,
}: {
  error: unknown
  retry: () => void
}) {
  const apiError = error instanceof ApiError ? error : null
  const state =
    apiError?.status === 401
      ? {
          icon: LogInIcon,
          title: "需要管理会话",
          description:
            "请先通过现有后台认证建立会话。本版本不提供独立登录页，也不会展示模拟应用。",
        }
      : apiError?.status === 403
        ? {
            icon: LockKeyholeIcon,
            title: "没有业务应用权限",
            description:
              "当前用户没有读取业务应用的权限。请联系平台管理员分配 business_application.read。",
          }
        : apiError?.code === "business_application_control_plane_disabled"
          ? {
              icon: ToggleLeftIcon,
              title: "业务应用控制面未开启",
              description:
                "后端功能开关当前关闭。开启后才会暴露真实业务应用管理入口。",
            }
          : apiError?.status === 404
            ? {
                icon: AlertTriangleIcon,
                title: "业务应用不存在或不可见",
                description:
                  "目标应用不存在，或当前用户无权读取。系统不会泄露不可见应用信息。",
              }
            : {
                icon: ServerOffIcon,
                title: "管理服务不可用",
                description:
                  apiError?.message ??
                  "无法读取真实控制面数据。页面不会回退到静态 fixture。",
              }
  const Icon = state.icon
  return (
    <Card className="shadow-none">
      <CardContent className="flex min-h-72 flex-col items-center justify-center px-6 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-muted">
          <Icon className="size-5 text-muted-foreground" aria-hidden="true" />
        </span>
        <h2 className="mt-4 text-lg font-semibold">{state.title}</h2>
        <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
          {state.description}
        </p>
        <Button type="button" variant="outline" className="mt-5" onClick={retry}>
          重新加载
        </Button>
      </CardContent>
    </Card>
  )
}

