import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CodeIndexStatus } from "./code-index-status"

afterEach(() => vi.unstubAllGlobals())
function renderStatus() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <CodeIndexStatus resourceId="code-library" />
    </QueryClientProvider>
  )
}
function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("代码答案增量索引", () => {
  it("暂停和恢复只改变索引开关，失败任务可以单独重试", async () => {
    const value = {
      paused: false,
      indexes: [
        {
          id: "code-index",
          collection_name: "code-answers-only",
          profile_hash: "embedding",
          chunk_profile_hash: "code-chunks",
          counts: { succeeded: 2, failed: 1 },
          tasks: [
            {
              id: "task-one",
              action: "upsert",
              state: "failed",
              expected_chunks: 4,
              completed_chunks: 2,
              error_code: "CODE_INDEX_IO_FAILED",
            },
          ],
        },
      ],
    }
    const calls: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === "POST") {
          const body = JSON.parse(String(init.body))
          calls.push({ url, body })
          if (url.endsWith("/indexing")) value.paused = body.paused
          else value.indexes[0].tasks[0].state = "queued"
        }
        return response(value)
      })
    )
    renderStatus()
    expect(await screen.findByText("代码集合：code-answers-only")).toBeVisible()
    fireEvent.click(screen.getByRole("button", { name: "暂停增量索引" }))
    await screen.findByRole("button", { name: "恢复增量索引" })
    expect(calls[0]).toEqual({
      url: "/api/platform/knowledge/code/resources/code-library/indexing",
      body: { paused: true },
    })
    fireEvent.click(screen.getByRole("button", { name: "恢复增量索引" }))
    await screen.findByRole("button", { name: "暂停增量索引" })
    fireEvent.click(screen.getByRole("button", { name: "重试索引" }))
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "重试索引" })).toBeNull()
    )
    expect(calls[2]).toEqual({
      url: "/api/platform/knowledge/code/resources/code-library/index-tasks/task-one/retry",
      body: {},
    })
    expect(calls.every((call) => !/publish|sync|extract/.test(call.url))).toBe(
      true
    )
  })
  it("接口故障不能显示索引已完成或自动重试写入", async () => {
    const fetch = vi.fn(async () =>
      response({ error: { code: "unavailable" } }, 503)
    )
    vi.stubGlobal("fetch", fetch)
    renderStatus()
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "知识管理服务暂不可用"
    )
    expect(screen.queryByText(/已开启|已完成/)).toBeNull()
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
