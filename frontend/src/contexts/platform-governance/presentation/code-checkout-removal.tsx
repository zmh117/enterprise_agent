import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { createRequestKey } from "@/lib/request-key"
import { ApiError, apiRequest } from "@/shared/api/api-client"
import type { CheckoutInventory } from "../application/code-checkout-query"
import { codeCheckoutErrors } from "./code-checkout-errors"
import { KnowledgeError } from "./knowledge-resource-ui"

type Checkout = CheckoutInventory["checkouts"][number]
const states: Record<string, string> = {
  queued: "等待删除",
  running: "正在删除",
  succeeded: "已删除",
  failed: "删除失败",
  cancelled: "已取消",
  interrupted: "已中断",
}

export function CheckoutRemoval({
  resourceId,
  inventory,
  onQueued,
}: {
  resourceId: string
  inventory: CheckoutInventory
  onQueued?: (id: string) => void
}) {
  const cache = useQueryClient()
  const [confirm, setConfirm] = useState<Checkout>()
  const [missingOnly, setMissingOnly] = useState(false)
  const removal = useMutation({
    mutationFn: ({
      item,
      missingOnly,
    }: {
      item: Checkout
      missingOnly: boolean
    }) =>
      apiRequest(
        `/api/platform/knowledge/code/resources/${encodeURIComponent(resourceId)}/checkouts/${encodeURIComponent(item.id)}/remove`,
        {
          method: "POST",
          body: {
            generation: item.generation,
            request_key: createRequestKey(),
            ...(missingOnly ? { missing_only: true } : {}),
          },
        }
      ),
    onSuccess: (_, { item }) => {
      setConfirm(undefined)
      onQueued?.(item.id)
    },
    onSettled: () => cache.invalidateQueries({ queryKey: ["code-checkouts"] }),
  })
  const jobs = inventory.jobs.filter((job) => job.operation_kind === "retire")
  const current = inventory.checkouts.find((item) => item.id === confirm?.id)
  return (
    <details
      className="rounded border p-4 text-sm"
      data-testid="code-checkout-management"
    >
      <summary className="cursor-pointer font-medium">管理本地检出目录</summary>
      <ul className="mt-3 grid gap-2">
        {inventory.checkouts.map((item) => (
          <li
            key={item.id}
            className="flex flex-wrap items-center justify-between gap-2"
          >
            <span className="break-all">{item.relative_dir}</span>
            {item.removal_blocker === null ||
            item.removal_blocker === "CODE_CHECKOUT_IDENTITY_CHANGED" ? (
              <Button
                variant="outline"
                size="sm"
                disabled={removal.isPending}
                data-testid={`code-checkout-remove-${item.id}`}
                aria-label={`${item.removal_blocker ? "清理缺失目录登记" : "删除本地目录"} ${item.relative_dir}`}
                onClick={() => {
                  removal.reset()
                  setMissingOnly(item.removal_blocker !== null)
                  setConfirm(item)
                }}
              >
                {item.removal_blocker ? "清理缺失目录登记" : "删除"}
              </Button>
            ) : (
              <span className="text-muted-foreground">
                {codeCheckoutErrors[item.removal_blocker ?? ""] ??
                  "无法核实目录是否可删除。"}
              </span>
            )}
          </li>
        ))}
      </ul>
      {confirm && (
        <div className="mt-3 grid gap-2 rounded border p-3">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={missingOnly}
              disabled={removal.isPending || confirm.removal_blocker !== null}
              onChange={(event) => setMissingOnly(event.target.checked)}
            />
            仅清理缺失目录登记
          </label>
          <p>
            {missingOnly
              ? `确认清理「${confirm.relative_dir}」的登记？若目录或删除暂存路径仍存在，系统会保留登记。`
              : `永久删除本地目录「${confirm.relative_dir}」及其中的全部文件？SVN 仓库中的文件会保留。`}
          </p>
          <div className="flex gap-2">
            <Button
              variant="destructive"
              data-testid="code-checkout-confirm-removal"
              disabled={
                removal.isPending ||
                current?.generation !== confirm.generation ||
                (current.removal_blocker !== null &&
                  !(
                    missingOnly &&
                    current.removal_blocker === "CODE_CHECKOUT_IDENTITY_CHANGED"
                  ))
              }
              onClick={() => removal.mutate({ item: confirm, missingOnly })}
            >
              {missingOnly ? "确认清理缺失目录登记" : "确认删除本地目录"}
            </Button>
            <Button
              variant="outline"
              disabled={removal.isPending}
              onClick={() => {
                setConfirm(undefined)
                removal.reset()
              }}
            >
              取消
            </Button>
          </div>
        </div>
      )}
      {removal.error instanceof ApiError &&
      codeCheckoutErrors[removal.error.code.toUpperCase()] ? (
        <p role="alert">
          {codeCheckoutErrors[removal.error.code.toUpperCase()]}
        </p>
      ) : (
        <KnowledgeError error={removal.error} />
      )}
      {removal.isSuccess && <p role="status">已提交删除任务。</p>}
      {jobs.length > 0 && (
        <ul className="mt-3 grid gap-1" aria-label="目录删除记录">
          {jobs.map((job) => (
            <li key={job.id}>
              {job.result.relative_dir} ·{" "}
              {job.state === "succeeded" && job.result.directory_already_absent
                ? "本地目录已不存在，已清理登记"
                : (states[job.state] ?? job.state)}
              {job.error_code && (
                <span>
                  {" "}
                  ·{" "}
                  {codeCheckoutErrors[job.error_code.toUpperCase()] ??
                    job.error_code}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </details>
  )
}
