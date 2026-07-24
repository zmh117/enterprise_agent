import {
  ArrowRightIcon,
  BoxesIcon,
  Link2Icon,
  ShieldCheckIcon,
  UsersIcon,
} from "lucide-react"
import { Link } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function DashboardPage() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-7 px-4 py-5 sm:px-6 lg:px-8 lg:py-8">
      <section
        aria-labelledby="page-title"
        className="rounded-2xl border bg-card px-6 py-7 shadow-sm sm:px-8"
      >
        <div className="mb-3 flex items-center gap-2">
          <Badge variant="secondary">当前 MVP</Badge>
          <Badge variant="outline">真实控制面</Badge>
        </div>
        <h1
          id="page-title"
          className="text-2xl font-semibold tracking-tight sm:text-3xl"
        >
          Agent 应用平台
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground sm:text-base">
          当前界面只开放已经接入后端的业务应用，以及用户与外部身份管理。
          钉钉和 ONES 身份统一关联到系统用户，身份映射本身不会新增授权。
        </p>
      </section>

      <section
        className="grid gap-4 md:grid-cols-2"
        aria-label="可用管理模块"
      >
        <ModuleCard
          icon={BoxesIcon}
          title="业务应用"
          description="进入现有业务应用控制面，查看和维护已经接线的应用配置。"
          href="/applications"
          action="打开业务应用"
        />
        <ModuleCard
          icon={UsersIcon}
          title="用户与外部身份"
          description="创建和启停系统用户，并管理钉钉、ONES 外部身份的绑定与生命周期。"
          href="/users"
          action="管理用户身份"
        />
      </section>

      <Card className="shadow-none">
        <CardHeader>
          <div className="flex size-10 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
            <ShieldCheckIcon aria-hidden="true" />
          </div>
          <CardTitle>统一身份边界</CardTitle>
          <CardDescription>
            一个系统用户可关联多个受支持外部系统身份。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
          <BoundaryItem title="系统用户" detail="平台内唯一人员主体" />
          <BoundaryItem title="钉钉身份" detail="用于消息入口身份解析" />
          <BoundaryItem title="ONES 身份" detail="仅完成身份验证与映射" />
        </CardContent>
      </Card>
    </div>
  )
}

function ModuleCard({
  icon: Icon,
  title,
  description,
  href,
  action,
}: {
  icon: typeof BoxesIcon
  title: string
  description: string
  href: string
  action: string
}) {
  return (
    <Card className="shadow-none">
      <CardHeader>
        <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Icon aria-hidden="true" />
        </div>
        <CardTitle>{title}</CardTitle>
        <CardDescription className="min-h-10">{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          nativeButton={false}
          render={<Link to={href} />}
          className="w-full sm:w-auto"
        >
          {action}
          <ArrowRightIcon aria-hidden="true" />
        </Button>
      </CardContent>
    </Card>
  )
}

function BoundaryItem({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-xl border bg-muted/20 p-4">
      <Link2Icon
        className="mb-3 size-4 text-muted-foreground"
        aria-hidden="true"
      />
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
    </div>
  )
}
