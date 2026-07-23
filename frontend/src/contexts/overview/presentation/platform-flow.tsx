import { ArrowRightIcon, CheckIcon, ShieldXIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { forbiddenOperations, platformFlow } from "@/mocks/dashboard"
import { SectionHeading } from "@/shared/presentation/section-heading"

export function PlatformFlow() {
  return (
    <section aria-labelledby="platform-flow-title" className="space-y-4">
      <SectionHeading
        eyebrow="Target architecture"
        title="一次请求如何穿过平台"
        description="Agent Runtime 只看到受控业务能力；底层数据访问、认证、路由、脱敏与限流由独立 API 平台负责。"
      />

      <Card className="shadow-none">
        <CardContent className="p-4 sm:p-5">
          <ol className="grid gap-2 md:grid-cols-7" aria-label="平台调用链">
            {platformFlow.map((step, index) => (
              <li key={step.label} className="relative min-w-0">
                <div className="flex h-full min-h-24 flex-col rounded-lg border bg-background p-3">
                  <span className="mb-3 flex size-6 items-center justify-center rounded-full bg-indigo-600 text-[11px] font-semibold text-white">
                    {index + 1}
                  </span>
                  <span className="text-xs leading-4 font-semibold break-words">
                    {step.label}
                  </span>
                  <span className="mt-1 text-[11px] leading-4 text-muted-foreground">
                    {step.description}
                  </span>
                </div>
                {index < platformFlow.length - 1 ? (
                  <ArrowRightIcon
                    className="absolute top-1/2 -right-2.5 z-10 hidden size-4 -translate-y-1/2 rounded-full bg-background text-muted-foreground md:block"
                    aria-hidden="true"
                  />
                ) : null}
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="shadow-none">
          <CardHeader>
            <div className="flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                <CheckIcon className="size-4" aria-hidden="true" />
              </span>
              <div>
                <h3 className="font-semibold">Agent 平台的边界</h3>
                <p className="text-xs text-muted-foreground">
                  配置应用、流程、身份策略和 Capability
                </p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm sm:grid-cols-2">
            {[
              "创建业务应用",
              "装配 Agent Profile",
              "选择业务 Capability",
              "执行流程与投递",
              "记录调用审计",
              "传递可信主体上下文",
            ].map((item) => (
              <div
                key={item}
                className="flex items-center gap-2 rounded-md bg-muted/60 px-3 py-2"
              >
                <CheckIcon
                  className="size-3.5 text-emerald-600"
                  aria-hidden="true"
                />
                {item}
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="border-red-200/70 bg-red-50/30 shadow-none dark:border-red-900/50 dark:bg-red-950/20">
          <CardHeader>
            <div className="flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-lg bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300">
                <ShieldXIcon className="size-4" aria-hidden="true" />
              </span>
              <div>
                <h3 className="font-semibold">MVP 安全边界</h3>
                <p className="text-xs text-muted-foreground">
                  Agent Web 不配置数据库、Redis、Loki，也不持有底层连接凭据
                </p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {forbiddenOperations.map((item) => (
              <Badge key={item} variant="destructive" className="font-normal">
                禁止 · {item}
              </Badge>
            ))}
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
