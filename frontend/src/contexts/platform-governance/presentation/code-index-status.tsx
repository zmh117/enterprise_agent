import { useMutation, useQuery } from "@tanstack/react-query"
import { z } from "zod"
import { Button } from "@/components/ui/button"
import { apiRequest } from "@/shared/api/api-client"
import { KnowledgeError } from "./knowledge-resource-ui"

const statusSchema = z.object({
  paused: z.boolean(),
  indexes: z.array(
    z.object({
      id: z.string(),
      collection_name: z.string(),
      profile_hash: z.string(),
      chunk_profile_hash: z.string(),
      counts: z.record(z.string(), z.number()),
      tasks: z.array(
        z.object({
          id: z.string(),
          action: z.string(),
          state: z.string(),
          expected_chunks: z.number(),
          completed_chunks: z.number(),
          error_code: z.string().nullable(),
        })
      ),
    })
  ),
})
const stateLabels: Record<string, string> = {
  queued: "等待处理",
  running: "处理中",
  failed: "失败",
  cancelled: "已取消",
}

export function CodeIndexStatus({ resourceId }: { resourceId: string }) {
  const base = `/api/platform/knowledge/code/resources/${encodeURIComponent(resourceId)}`
  const status = useQuery({
    queryKey: ["code-index-status", resourceId],
    retry: false,
    refetchInterval: 3000,
    queryFn: async () =>
      statusSchema.parse(await apiRequest(`${base}/index-status`)),
  })
  const change = useMutation({
    mutationFn: async (command: { paused: boolean } | { taskId: string }) => {
      const retry = "taskId" in command
      return statusSchema.parse(
        await apiRequest(
          retry
            ? `${base}/index-tasks/${encodeURIComponent(command.taskId)}/retry`
            : `${base}/indexing`,
          { method: "POST", body: retry ? {} : command }
        )
      )
    },
    onSuccess: async () => {
      await status.refetch()
    },
  })
  return (
    <section className="grid gap-2" aria-label="代码答案增量索引">
      <KnowledgeError error={status.error ?? change.error} />
      {status.data && (
        <>
          <p>增量索引：{status.data.paused ? "已暂停" : "已开启"}</p>
          <p className="text-sm text-muted-foreground">
            暂停期间仍保存回答；恢复后继续处理待索引内容。已就绪内容可继续检索。
          </p>
          <Button
            variant="outline"
            disabled={change.isPending}
            onClick={() => change.mutate({ paused: !status.data!.paused })}
          >
            {status.data.paused ? "恢复增量索引" : "暂停增量索引"}
          </Button>
          {status.data.indexes.map((index) => (
            <div key={index.id} className="grid gap-1 rounded border p-3">
              <p className="text-sm break-all">
                代码集合：{index.collection_name}
              </p>
              <details className="text-sm break-all">
                <summary>查看分块与 Embedding 配置标识</summary>
                <p>分块 profile：{index.chunk_profile_hash}</p>
                <p>Embedding profile：{index.profile_hash}</p>
              </details>
              <p className="text-sm">
                已完成 {index.counts.succeeded ?? 0} · 等待{" "}
                {index.counts.queued ?? 0} · 处理中 {index.counts.running ?? 0}{" "}
                · 失败 {index.counts.failed ?? 0}
              </p>
              {index.tasks.map((task) => (
                <div
                  key={task.id}
                  className="flex flex-wrap items-center gap-2 text-sm"
                >
                  <span>
                    {task.action === "remove" ? "清理旧索引" : "索引答案"} ·{" "}
                    {stateLabels[task.state] ?? task.state} · 分块{" "}
                    {task.completed_chunks}/{task.expected_chunks}
                  </span>
                  {task.error_code && <span>原因：{task.error_code}</span>}
                  {task.state === "failed" && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={change.isPending}
                      onClick={() => change.mutate({ taskId: task.id })}
                    >
                      重试索引
                    </Button>
                  )}
                </div>
              ))}
            </div>
          ))}
        </>
      )}
    </section>
  )
}
