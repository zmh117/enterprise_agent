import { Component, type ReactNode } from "react"
import { RefreshCwIcon, TriangleAlertIcon } from "lucide-react"

import { Button, buttonVariants } from "@/components/ui/button"


type AppErrorBoundaryState = { failed: boolean }

export class AppErrorBoundary extends Component<
  { children: ReactNode },
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true }
  }

  render() {
    if (!this.state.failed) return this.props.children
    return <AppErrorFallback />
  }
}

export function AppErrorFallback() {
  return (
    <main className="flex min-h-svh items-center justify-center bg-background p-6">
      <section className="flex max-w-lg flex-col items-center gap-4 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-amber-100 text-amber-700">
          <TriangleAlertIcon aria-hidden="true" />
        </span>
        <div>
          <h1 className="text-xl font-semibold">管理页面暂时无法显示</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            页面遇到意外错误。你可以安全刷新，或返回工作台重新进入。
          </p>
        </div>
        <div className="flex gap-3">
          <Button onClick={() => window.location.reload()}>
            <RefreshCwIcon aria-hidden="true" />
            刷新页面
          </Button>
          <a href="/" className={buttonVariants({ variant: "outline" })}>
            返回工作台
          </a>
        </div>
      </section>
    </main>
  )
}
