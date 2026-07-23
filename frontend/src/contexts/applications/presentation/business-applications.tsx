import { ArrowUpRightIcon, BoxesIcon, CheckCircle2Icon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { applicationWorkspaces, businessApplications } from "@/mocks/dashboard"
import { DisabledAction } from "@/shared/presentation/disabled-action"
import { SectionHeading } from "@/shared/presentation/section-heading"

const tones = {
  indigo:
    "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
  cyan: "bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300",
  amber: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
} as const

export function BusinessApplications() {
  return (
    <section
      aria-labelledby="business-applications-title"
      className="space-y-4"
    >
      <SectionHeading
        eyebrow="Primary object"
        title="业务应用"
        description="业务应用装配 Profile、Workflow、Channel、Capability 和发布快照；三个应用共享同一套 Agent Runtime。"
        prototype
        action={
          <DisabledAction variant="outline" size="sm">
            新建应用 · 规划中
          </DisabledAction>
        }
      />

      <div className="grid gap-4 xl:grid-cols-3">
        {businessApplications.map((application) => {
          const Icon = application.icon
          return (
            <Card key={application.id} className="shadow-none">
              <CardHeader className="border-b">
                <div className="flex items-start justify-between gap-3">
                  <span
                    className={`flex size-10 items-center justify-center rounded-xl ${tones[application.tone]}`}
                  >
                    <Icon className="size-5" aria-hidden="true" />
                  </span>
                  <Badge variant="outline" className="font-normal">
                    {application.release}
                  </Badge>
                </div>
                <div className="mt-2">
                  <h3 className="text-base font-semibold">
                    {application.name}
                  </h3>
                  <p className="mt-1 min-h-12 text-sm leading-6 text-muted-foreground">
                    {application.description}
                  </p>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <Definition label="Agent Profile" value={application.profile} />
                <Definition label="Workflow" value={application.workflow} />
                <Definition label="触发器" value={application.trigger} />
                <Definition label="输出渠道" value={application.delivery} />
                <Definition label="身份策略" value={application.identity} />
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Badge className="bg-indigo-50 text-indigo-700 hover:bg-indigo-50 dark:bg-indigo-950 dark:text-indigo-300">
                    {application.capabilities} 个只读 Capability
                  </Badge>
                  <Badge variant="secondary">{application.environment}</Badge>
                </div>
                <DisabledAction variant="outline" className="mt-1 w-full">
                  查看应用工作区 · 规划中
                  <ArrowUpRightIcon data-icon="inline-end" />
                </DisabledAction>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Card className="shadow-none">
        <CardHeader>
          <div className="flex items-center gap-2">
            <BoxesIcon className="size-4 text-indigo-600" aria-hidden="true" />
            <h3 className="font-semibold">应用工作区目标结构</h3>
            <Badge variant="outline" className="ml-auto">
              仅展示关系
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-5">
          {applicationWorkspaces.map((workspace, index) => (
            <div
              key={workspace.name}
              className="rounded-lg border bg-muted/35 p-3"
            >
              <div className="flex items-center gap-2">
                <CheckCircle2Icon
                  className="size-3.5 text-indigo-600"
                  aria-hidden="true"
                />
                <span className="text-sm font-medium">
                  {index + 1}. {workspace.name}
                </span>
              </div>
              <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
                {workspace.description}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  )
}

function Definition({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] gap-3 text-xs">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-right font-medium" title={value}>
        {value}
      </dd>
    </div>
  )
}
