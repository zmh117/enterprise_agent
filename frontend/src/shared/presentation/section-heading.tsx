import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"

type SectionHeadingProps = {
  eyebrow?: string
  title: string
  description: string
  action?: ReactNode
  prototype?: boolean
}

export function SectionHeading({
  eyebrow,
  title,
  description,
  action,
  prototype = false,
}: SectionHeadingProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {eyebrow ? (
            <span className="text-xs font-semibold tracking-[0.12em] text-primary uppercase">
              {eyebrow}
            </span>
          ) : null}
          {prototype ? <Badge variant="outline">原型数据</Badge> : null}
        </div>
        <h2 className="mt-1 text-lg font-semibold tracking-tight text-foreground">
          {title}
        </h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
          {description}
        </p>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}
