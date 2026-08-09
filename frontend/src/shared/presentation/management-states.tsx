import type { ReactNode } from "react"
import { AlertTriangleIcon, RefreshCwIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError } from "@/shared/api/api-client"

export function ManagementPage({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-7xl space-y-5 p-4 sm:p-6">
      {children}
    </main>
  )
}

export function ManagementLoading({
  label = "正在加载管理数据",
}: {
  label?: string
}) {
  return (
    <div aria-label={label} aria-busy="true" className="space-y-4">
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  )
}

export function ManagementError({
  error,
  retry,
}: {
  error: unknown
  retry: () => void
}) {
  if (!error) return null
  const message =
    error instanceof ApiError ? error.message : "管理数据加载失败。"
  return (
    <Card role="alert" className="border-destructive/40 shadow-none">
      <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
        <p className="flex items-center gap-2 text-sm">
          <AlertTriangleIcon
            className="size-4 text-destructive"
            aria-hidden="true"
          />
          {message}
        </p>
        <Button type="button" variant="outline" onClick={retry}>
          <RefreshCwIcon />
          重试
        </Button>
      </CardContent>
    </Card>
  )
}

export function MutationNotice({ error }: { error: unknown }) {
  if (!error) return null
  const apiError = error instanceof ApiError ? error : null
  return (
    <div
      role="alert"
      className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm"
    >
      <p>{apiError?.message ?? "操作失败，请稍后重试。"}</p>
      {apiError?.code === "revision_conflict" ? (
        <p className="mt-1 text-muted-foreground">
          当前版本已变化
          {apiError.currentRevision !== undefined
            ? `（最新版本 ${apiError.currentRevision}）`
            : ""}
          ，请刷新后比较再提交。
        </p>
      ) : null}
      {apiError?.fieldErrors.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {apiError.fieldErrors.map((item, index) => (
            <li key={`${item.field}-${index}`}>
              {item.field}: {item.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
