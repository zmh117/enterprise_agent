import { ArrowDownIcon, BotIcon, BracesIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { workflowPreviews } from "@/mocks/dashboard"
import { DisabledAction } from "@/shared/presentation/disabled-action"

export function WorkflowPreview() {
  return (
    <Card className="shadow-none">
      <CardHeader className="border-b">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <BracesIcon
                className="size-4 text-indigo-600"
                aria-hidden="true"
              />
              <h3 className="font-semibold">Workflow 预览</h3>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              固定 API 节点保证确定性；Agent 节点只在授权集合中自主选择能力。
            </p>
          </div>
          <DisabledAction size="xs" variant="outline">
            编辑流程 · 规划中
          </DisabledAction>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 xl:grid-cols-3">
        {workflowPreviews.map((workflow) => (
          <article
            key={workflow.name}
            className="rounded-lg border bg-muted/25 p-3"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-semibold">{workflow.name}</h4>
              <Badge variant="secondary" className="font-normal">
                {workflow.mode}
              </Badge>
            </div>
            <ol className="mt-3 space-y-1" aria-label={`${workflow.name}流程`}>
              {workflow.steps.map((step, index) => {
                const isAgent = step.includes("Agent")
                const isFixed = step.includes("固定 API")
                return (
                  <li key={step}>
                    <div
                      className={`flex items-center gap-2 rounded-md border px-2.5 py-2 text-xs ${isAgent ? "border-indigo-200 bg-indigo-50/70 dark:border-indigo-900 dark:bg-indigo-950/40" : isFixed ? "border-cyan-200 bg-cyan-50/70 dark:border-cyan-900 dark:bg-cyan-950/40" : "bg-background"}`}
                    >
                      {isAgent ? (
                        <BotIcon
                          className="size-3.5 text-indigo-600"
                          aria-hidden="true"
                        />
                      ) : (
                        <span className="flex size-4 items-center justify-center rounded-full bg-muted text-[9px] font-semibold">
                          {index + 1}
                        </span>
                      )}
                      <span className="leading-4">{step}</span>
                    </div>
                    {index < workflow.steps.length - 1 ? (
                      <ArrowDownIcon
                        className="mx-auto my-0.5 size-3 text-muted-foreground"
                        aria-hidden="true"
                      />
                    ) : null}
                  </li>
                )
              })}
            </ol>
          </article>
        ))}
      </CardContent>
    </Card>
  )
}
