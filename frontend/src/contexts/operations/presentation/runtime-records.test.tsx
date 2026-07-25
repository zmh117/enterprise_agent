import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import {
  ConversationDetailPage,
  RuntimeJobDetailPage,
  RuntimeRecordsPage,
} from "@/contexts/operations/presentation/runtime-records-page"

function response(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  )
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    session_id: "session-1",
    status: "SUCCEEDED",
    project_code: "default",
    source_channel: "dingding_stream",
    source_connector_id: "connector-dingtalk-stream-default",
    agent_code: "default-diagnostic-agent",
    correlation_id: "correlation-1",
    business_application_id: "application-1",
    business_application_code: "diagnostic-app",
    business_application_publication_id: "publication-1",
    business_application_deployment_id: "deployment-1",
    business_application_route_id: "route-1",
    business_application_runtime_status: "partially_wired",
    business_application_route_decision: {},
    execution_policy: {
      schema_version: 1,
      requested: {
        max_turns: 20,
        timeout_seconds: 300,
        max_tool_calls: 10,
      },
      effective: {
        max_turns: 12,
        timeout_seconds: 300,
        max_tool_calls: 10,
      },
      sources: {
        source_kind: "business_application",
        agent_publication_id: "agent-publication-1",
      },
    },
    tool_call_count: 3,
    execution_policy_exhausted: false,
    last_error_code: "",
    created_at: "2026-07-24T10:00:00+00:00",
    ...overrides,
  }
}

function renderRoute(
  path: string,
  routePattern: string,
  element: React.ReactNode
) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={routePattern} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe("runtime provenance records", () => {
  it("shows attributed and legacy jobs without guessing ownership", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        items: [
          job(),
          job({
            id: "job-legacy",
            business_application_id: "",
            business_application_code: "",
            business_application_publication_id: "",
            business_application_runtime_status: "legacy_unattributed",
          }),
        ],
        page: { limit: 50, has_more: false, next_cursor: null },
      })
    )
    renderRoute("/operations/jobs", "/operations/jobs", <RuntimeRecordsPage />)
    expect(await screen.findByText("diagnostic-app")).toBeInTheDocument()
    expect(
      screen.getByText("历史兼容任务（无业务应用归因）")
    ).toBeInTheDocument()
    expect(screen.getAllByText("legacy_unattributed").length).toBeGreaterThan(0)
  })

  it("shows immutable application provenance in job detail", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job(),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        delivery_attempts: [],
        webhook_events: [],
      })
    )
    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )
    expect(await screen.findByText("Job 运行归因")).toBeInTheDocument()
    expect(screen.getByText("publication-1")).toBeInTheDocument()
    expect(screen.getByText("deployment-1")).toBeInTheDocument()
    expect(screen.getByText("route-1")).toBeInTheDocument()
    expect(
      screen.getByText("12 轮 · 300 秒 · 10 次工具调用")
    ).toBeInTheDocument()
    expect(screen.getByText("agent-publication-1")).toBeInTheDocument()
  })

  it("shows application-scoped conversation policy and job provenance", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        session: {
          id: "session-1",
          requester_id: "user-1",
          source_channel: "dingding_stream",
          source_connector_id: "connector-dingtalk-stream-default",
          external_conversation_id: "conversation-1",
          business_application_id: "application-1",
          business_application_code: "diagnostic-app",
          conversation_mode: "channel",
          recent_message_limit: 20,
          created_at: "2026-07-24T10:00:00+00:00",
          updated_at: "2026-07-24T10:00:00+00:00",
        },
        jobs: [
          job(),
          job({
            id: "job-with-a-very-long-identifier-that-must-not-break-the-layout",
            business_application_publication_id:
              "business_app_publication_with_a_very_long_identifier",
          }),
        ],
        messages: [],
      })
    )
    renderRoute(
      "/operations/conversations/session-1",
      "/operations/conversations/:sessionId",
      <ConversationDetailPage />
    )
    expect(await screen.findByText("会话归因")).toBeInTheDocument()
    expect(screen.getAllByText("diagnostic-app").length).toBeGreaterThan(0)
    expect(screen.getByText("channel")).toBeInTheDocument()
    expect(
      screen.getByRole("list", { name: "会话内 Job 列表" })
    ).toBeInTheDocument()
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
    expect(screen.getByText("2 个")).toBeInTheDocument()
    expect(
      screen.getByText("business_app_publication_with_a_very_long_identifier")
    ).toBeInTheDocument()
  })
})
