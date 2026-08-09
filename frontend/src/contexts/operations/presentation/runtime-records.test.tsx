import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  ConversationDetailPage,
  RuntimeJobDetailPage,
  RuntimeRecordsPage,
} from "@/contexts/operations/presentation/runtime-records-page"

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }))
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    session_id: "session-1",
    status: "SUCCEEDED",
    source_channel: "dingtalk_stream",
    source_connector_id: "connector-1",
    agent_code: "diagnostic-agent",
    correlation_id: "correlation-1",
    execution_policy: { schema_version: 1, requested: {}, effective: {}, sources: {} },
    tool_call_count: 1,
    execution_policy_exhausted: false,
    last_error_code: "",
    error_summary: "",
    created_at: "2026-08-08T10:00:00+08:00",
    finished_at: "2026-08-08T10:00:03+08:00",
    ...overrides,
  }
}

function renderRoute(path: string, pattern: string, element: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}><Routes><Route path={pattern} element={element} /></Routes></MemoryRouter>
    </QueryClientProvider>
  )
}

afterEach(() => vi.restoreAllMocks())

describe("MCP 历史与本人隔离", () => {
  it("Job 列表只调用本人历史接口", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => response({ items: [job()], page: { limit: 50, has_more: false, next_cursor: null } }))
    renderRoute("/operations/jobs", "/operations/jobs", <RuntimeRecordsPage />)
    expect(await screen.findByText("job-1")).toBeInTheDocument()
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/me/jobs?limit=50", expect.any(Object)))
    expect(fetch.mock.calls.some(([input]) => String(input).startsWith("/api/admin/"))).toBe(false)
  })

  it("详情展示脱敏 MCP provenance 而不是旧 Capability 归因", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => response({
      job: job(),
      session_ref: { id: "session-1" },
      dispatch: null,
      steps: [{ id: "step-1", title: "分析", content: "已完成" }],
      mcp_tool_calls: [{
        id: "mcp-1",
        job_id: "job-1",
        mcp_server_code: "ones-mcp",
        server_version: "2.0.0",
        tool_name: "ones_work_item_search",
        tool_schema_hash: "a".repeat(64),
        subject_snapshot_id: "subject-snapshot-1",
        resource_deployment_id: "",
        resource_revision_id: "",
        credential_revision: 3,
        request_summary: { query_kind: "work_item_search", limit: 20 },
        result_hash: "b".repeat(64),
        result_size: 128,
        status: "SUCCEEDED",
        duration_ms: 42,
        correlation_id: "correlation-1",
        occurred_at: "2026-08-08T10:00:01+08:00",
        attempts: [{ attempt: 1, status: "SUCCEEDED", error_code: "", duration_ms: 42, created_at: "2026-08-08T10:00:01+08:00" }],
      }],
      deliveries: { events: [], attempts: [], chunks: [] },
    }))
    renderRoute("/operations/jobs/job-1", "/operations/jobs/:jobId", <RuntimeJobDetailPage />)
    expect(await screen.findByRole("heading", { name: "Job 运行证据" })).toBeInTheDocument()
    expect(screen.getByText("ones-mcp@2.0.0")).toBeInTheDocument()
    expect(screen.getByText("ones_work_item_search")).toBeInTheDocument()
    expect(screen.getByText("r3")).toBeInTheDocument()
    expect(document.body.textContent).not.toContain("password")
    expect(document.body.textContent).not.toContain("Authorization")
    expect(document.body.textContent).not.toContain("Capability")
  })

  it("Agent 成功不会把待处理 Delivery 误报为已送达", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => response({
      job: job(), session_ref: { id: "session-1" }, dispatch: null, steps: [], mcp_tool_calls: [],
      deliveries: { events: [{ id: "delivery-1", status: "PENDING", delivery_kind: "result", route_type: "dingtalk_private", attempt_count: 0, last_error_code: "", last_error_summary: "", created_at: "2026-08-08T10:00:02+08:00", updated_at: "2026-08-08T10:00:02+08:00" }], attempts: [], chunks: [] },
    }))
    renderRoute("/operations/jobs/job-1", "/operations/jobs/:jobId", <RuntimeJobDetailPage />)
    expect(await screen.findByText("PENDING")).toBeInTheDocument()
    expect(screen.queryByText("已送达")).not.toBeInTheDocument()
  })

  it("会话详情使用本人接口并展示同会话 Job", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => response({
      session: { id: "session-1", requester_id: "user-1", source_channel: "dingtalk_stream", source_connector_id: "connector-1", external_conversation_id: "conversation-1", created_at: "2026-08-08T10:00:00+08:00", updated_at: "2026-08-08T10:00:00+08:00" },
      jobs: [job()],
      messages: [{ id: "message-1", role: "user", content: "查看我的任务" }],
    }))
    renderRoute("/operations/conversations/session-1", "/operations/conversations/:sessionId", <ConversationDetailPage />)
    expect(await screen.findByRole("heading", { name: "本人会话" })).toBeInTheDocument()
    expect(screen.getByText("查看我的任务")).toBeInTheDocument()
    expect(screen.getByText("job-1")).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith("/api/me/conversations/session-1", expect.any(Object))
  })
})
