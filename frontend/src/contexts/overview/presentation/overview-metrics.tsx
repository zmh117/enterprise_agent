import { ActivityIcon, BotIcon, BoxesIcon, CableIcon } from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"
import { overviewMetrics } from "@/mocks/dashboard"

const metricIcons = [BoxesIcon, BotIcon, CableIcon, ActivityIcon]

export function OverviewMetrics() {
  return (
    <section aria-labelledby="overview-metrics-title">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="overview-metrics-title" className="text-sm font-semibold">
          平台概览
        </h2>
        <span className="text-xs text-muted-foreground">静态原型指标</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {overviewMetrics.map((metric, index) => {
          const Icon = metricIcons[index]
          return (
            <Card key={metric.label} size="sm" className="shadow-none">
              <CardContent className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium text-muted-foreground">
                    {metric.label}
                  </p>
                  <p className="mt-2 text-2xl font-semibold tracking-tight">
                    {metric.value}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {metric.note}
                  </p>
                </div>
                <span className="flex size-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </section>
  )
}
