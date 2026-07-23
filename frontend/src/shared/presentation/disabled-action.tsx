import { Children, type ComponentProps } from "react"

import { Button } from "@/components/ui/button"

type DisabledActionProps = Omit<ComponentProps<typeof Button>, "disabled"> & {
  reason?: string
}

export function DisabledAction({
  children,
  reason = "静态界面原型，业务操作将在后续变更中实现",
  ...props
}: DisabledActionProps) {
  const visibleLabel = Children.toArray(children)
    .filter((child) => typeof child === "string" || typeof child === "number")
    .join("")
    .trim()

  return (
    <Button
      disabled
      title={reason}
      aria-label={`${visibleLabel || "不可用业务操作"}，规划中`}
      {...props}
    >
      {children}
    </Button>
  )
}
