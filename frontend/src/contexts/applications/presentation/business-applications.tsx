import { ArrowRightIcon, BoxesIcon } from "lucide-react"
import { Link } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { SectionHeading } from "@/shared/presentation/section-heading"

export function BusinessApplications() {
  return (
    <section
      aria-labelledby="business-applications-title"
      className="space-y-4"
    >
      <SectionHeading
        eyebrow="Primary object"
        title="业务应用"
        description="业务应用真实工作区已经连接后端控制面；Dashboard 不再展示静态应用 fixture。"
        action={
          <Link
            to="/applications"
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            打开业务应用
            <ArrowRightIcon data-icon="inline-end" />
          </Link>
        }
      />
      <Card className="shadow-none">
        <CardHeader className="flex-row items-center gap-3 border-b">
          <span className="flex size-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700">
            <BoxesIcon className="size-5" aria-hidden="true" />
          </span>
          <div>
            <h3 className="font-semibold">控制面事实来自管理 API</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              列表、草稿、校验、publication 和环境 deployment
              均在独立页面读取真实数据。
            </p>
          </div>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Badge variant="secondary">追加式 revision</Badge>
          <Badge variant="secondary">不可变 publication</Badge>
          <Badge variant="secondary">环境级 activation</Badge>
          <Badge variant="outline">runtime_wired=false</Badge>
        </CardContent>
      </Card>
    </section>
  )
}
