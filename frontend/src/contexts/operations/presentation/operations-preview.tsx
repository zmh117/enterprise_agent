import {
  ActivityIcon,
  CheckCircle2Icon,
  CircleDashedIcon,
  Clock3Icon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { buildStatuses, sampleRuns } from "@/mocks/dashboard"

const buildTone: Record<string, string> = {
  indigo:
    "border-indigo-200 bg-indigo-50/60 dark:border-indigo-900 dark:bg-indigo-950/30",
  emerald:
    "border-emerald-200 bg-emerald-50/60 dark:border-emerald-900 dark:bg-emerald-950/30",
  amber:
    "border-amber-200 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/30",
  slate:
    "border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900/50",
}

export function OperationsPreview() {
  return (
    <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
      <Card className="shadow-none">
        <CardHeader className="border-b">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <ActivityIcon
                className="size-4 text-indigo-600"
                aria-hidden="true"
              />
              <h3 className="font-semibold">运行中心预览</h3>
            </div>
            <Badge variant="outline">示例记录 · 非实时</Badge>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="divide-y">
            {sampleRuns.map((run) => (
              <div
                key={run.id}
                className="grid gap-2 px-4 py-3 text-xs sm:grid-cols-[1fr_1.5fr_1fr_auto] sm:items-center"
              >
                <div>
                  <p className="font-mono text-[11px] font-medium">{run.id}</p>
                  <p className="mt-1 text-muted-foreground">{run.actor}</p>
                </div>
                <p className="font-medium">{run.app}</p>
                <Badge variant="secondary" className="w-fit font-normal">
                  {run.status}
                </Badge>
                <div className="flex items-center gap-1 text-muted-foreground">
                  <Clock3Icon className="size-3" aria-hidden="true" />
                  {run.duration}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="shadow-none">
        <CardHeader className="border-b">
          <div className="flex items-center gap-2">
            <CircleDashedIcon
              className="size-4 text-indigo-600"
              aria-hidden="true"
            />
            <h3 className="font-semibold">建设状态</h3>
          </div>
          <p className="text-xs text-muted-foreground">
            区分页面概念、已有基础和真实交付状态。
          </p>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2">
          {buildStatuses.map((status) => (
            <div
              key={status.label}
              className={`rounded-lg border p-3 ${buildTone[status.tone]}`}
            >
              <div className="flex items-center gap-2 text-xs font-semibold">
                <CheckCircle2Icon className="size-3.5" aria-hidden="true" />
                {status.label}
              </div>
              <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
                {status.items}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
