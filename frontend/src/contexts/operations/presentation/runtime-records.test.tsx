import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
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
    execution_summary: executionSummary(),
    created_at: "2026-07-24T10:00:00+00:00",
    ...overrides,
  }
}

function executionSummary(overrides: Record<string, unknown> = {}) {
  return {
    accounting_status: "COMPLETE",
    observed_model_turn_count: 1,
    api_retry_count: 1,
    runtime_invocation_count: 1,
    total_duration_ms: 2400,
    total_api_duration_ms: 1800,
    input_tokens: 120,
    output_tokens: 32,
    cache_creation_input_tokens: 8,
    cache_read_input_tokens: 16,
    model_usage: [],
    models: ["claude-safe-model"],
    estimated_cost_usd: "0.012345000000",
    execution_status: "SUCCEEDED",
    delivery_status: "NOT_REQUESTED",
    execution_failure_stage: null,
    display_failure_stage: null,
    failure_code: null,
    failure_summary: null,
    retry_exhausted: false,
    source_protocol_version: "1.2",
    ...overrides,
  }
}

function deliveryEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: "delivery-1",
    job_id: "job-1",
    result_artifact_id: "artifact-1",
    application_publication_id: "publication-1",
    route_type: "dingtalk_private",
    connector_id: "connector-dingtalk-stream-default",
    delivery_kind: "result",
    target_summary: {
      route_type: "dingtalk_private",
      connector_id: "connector-dingtalk-stream-default",
      target: { conversation_id: "***" },
    },
    correlation_id: "correlation-1",
    status: "PENDING",
    attempt_count: 0,
    max_attempts: 8,
    replay_count: 0,
    max_replay_count: 3,
    next_attempt_at: "2026-07-24T10:01:00+00:00",
    last_error_code: "",
    last_error_summary: "",
    started_at: null,
    finished_at: null,
    dead_at: null,
    last_replayed_at: null,
    created_at: "2026-07-24T10:00:10+00:00",
    updated_at: "2026-07-24T10:00:10+00:00",
    terminal: false,
    delivered: false,
    ...overrides,
  }
}

function modelCall(overrides: Record<string, unknown> = {}) {
  return {
    id: "model-call-1",
    job_id: "job-1",
    invocation_id: "invocation-1",
    request_digest: "a".repeat(64),
    runtime_sequence: 3,
    provider_request_id: "request-safe-1",
    provider_message_id: "message-safe-1",
    model_id: "claude-safe-model",
    status: "SUCCEEDED",
    started_at: "2026-07-24T10:00:00+00:00",
    completed_at: "2026-07-24T10:00:01+00:00",
    duration_ms: 1000,
    duration_source: "SDK_OBSERVED",
    input_tokens: 120,
    output_tokens: 32,
    cache_creation_input_tokens: 8,
    cache_read_input_tokens: 16,
    stop_reason: "end_turn",
    error_code: null,
    error_summary: null,
    created_at: "2026-07-24T10:00:01+00:00",
    updated_at: "2026-07-24T10:00:01+00:00",
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
    expect(screen.getAllByText(/总耗时 2.40 秒/).length).toBeGreaterThan(0)
    expect(screen.getAllByText("claude-safe-model").length).toBeGreaterThan(0)
  })

  it("shows immutable application provenance in job detail", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job(),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        execution_summary: executionSummary(),
        model_calls: {
          items: [modelCall()],
          limit: 50,
          has_more: false,
          next_cursor: null,
        },
        deliveries: { events: [], attempts: [], chunks: [] },
        webhook_events: [],
      })
    )
    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )
    expect(await screen.findByText("任务运行归因")).toBeInTheDocument()
    expect(screen.getByText("publication-1")).toBeInTheDocument()
    expect(screen.getByText("deployment-1")).toBeInTheDocument()
    expect(screen.getByText("route-1")).toBeInTheDocument()
    expect(
      screen.getByText("12 轮 · 300 秒 · 10 次工具调用")
    ).toBeInTheDocument()
    expect(screen.getByText("agent-publication-1")).toBeInTheDocument()
    expect(screen.getAllByText("claude-safe-model").length).toBeGreaterThan(0)
    expect(screen.getByText("Request request-safe-1")).toBeInTheDocument()
    expect(screen.getByText("Message message-safe-1")).toBeInTheDocument()
    expect(screen.getByText(/缓存创建 8/)).toBeInTheDocument()
    expect(screen.getByText(/缓存读取 16/)).toBeInTheDocument()
    expect(screen.getByText("停止 end_turn")).toBeInTheDocument()
    expect(screen.getByText("SDK 观测 · 1.00 秒")).toBeInTheDocument()
    expect(screen.getByText("1 次 API 重试")).toBeInTheDocument()
  })

  it("loads the next model-call page without replacing prior rows", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/model-calls?")) {
        return response({
          job_id: "job-1",
          items: [
            modelCall({
              id: "model-call-2",
              runtime_sequence: 10,
              model_id: "claude-safe-model-next",
              provider_request_id: "request-safe-2",
            }),
          ],
          limit: 50,
          has_more: false,
          next_cursor: null,
        })
      }
      return response({
        job: job(),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        execution_summary: executionSummary(),
        model_calls: {
          items: [modelCall()],
          limit: 50,
          has_more: true,
          next_cursor: "opaque-cursor-1",
        },
        deliveries: { events: [], attempts: [], chunks: [] },
        webhook_events: [],
      })
    })
    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )

    fireEvent.click(await screen.findByRole("button", { name: "加载更多模型请求" }))

    expect(await screen.findByText("claude-safe-model-next")).toBeInTheDocument()
    expect(screen.getAllByText("claude-safe-model").length).toBeGreaterThan(0)
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("cursor=opaque-cursor-1"),
        expect.anything()
      )
    )
    expect(
      screen.queryByRole("button", { name: "加载更多模型请求" })
    ).not.toBeInTheDocument()
  })

  it.each([
    ["TOOL_PERMISSION", "工具权限", "DENIED"],
    ["TOOL_EXECUTION", "工具执行", "FAILED"],
  ])(
    "shows partial accounting, unavailable turn duration and %s failure",
    async (failureStage, failureLabel, toolStatus) => {
      vi.spyOn(globalThis, "fetch").mockImplementation(() =>
        response({
          job: job({ status: "FAILED" }),
          session_ref: { id: "session-1" },
          steps: [],
          tool_calls: [
            {
              id: "tool-call-1",
              tool_name: "governed_safe_tool",
              status: toolStatus,
              response_summary: "安全摘要",
            },
          ],
          mcp_operation_links: [
            {
              agent_tool_call_id: "tool-call-1",
              mcp_call_id: "mcp-call-safe-1",
              server_code: "tool-mcp",
            },
          ],
          execution_summary: executionSummary({
            accounting_status: "PARTIAL",
            execution_status: "FAILED",
            execution_failure_stage: failureStage,
            display_failure_stage: failureStage,
            retry_exhausted: true,
          }),
          model_calls: {
            items: [
              modelCall({
                duration_ms: null,
                duration_source: "UNAVAILABLE",
              }),
            ],
            limit: 50,
            has_more: false,
            next_cursor: null,
          },
          deliveries: { events: [], attempts: [], chunks: [] },
          webhook_events: [],
        })
      )
      renderRoute(
        "/operations/jobs/job-1",
        "/operations/jobs/:jobId",
        <RuntimeJobDetailPage />
      )

      expect(await screen.findByText("统计部分可用")).toBeInTheDocument()
      expect(
        screen.getByText(new RegExp(`失败位置 ${failureLabel}`))
      ).toBeInTheDocument()
      expect(screen.getByText("Job 重试已耗尽", { exact: false })).toBeInTheDocument()
      expect(screen.getByText("不可用")).toBeInTheDocument()
      expect(
        screen.getByText(`governed_safe_tool · ${toolStatus}`)
      ).toBeInTheDocument()
      expect(screen.getByText("tool-mcp · mcp-call-safe-1")).toBeInTheDocument()
      expect(screen.queryByText(/SDK 观测 ·/)).not.toBeInTheDocument()
    }
  )

  it("keeps execution success separate when Delivery fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job(),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        execution_summary: executionSummary({
          delivery_status: "FAILED",
          display_failure_stage: "DELIVERY",
        }),
        model_calls: { items: [], limit: 50, has_more: false, next_cursor: null },
        deliveries: {
          events: [
            deliveryEvent({
              status: "FAILED",
              last_error_code: "delivery_failed",
              last_error_summary: "安全投递失败摘要",
              terminal: true,
            }),
          ],
          attempts: [],
          chunks: [],
        },
        webhook_events: [],
      })
    )
    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )

    expect(await screen.findByText("Agent 执行 SUCCEEDED · Delivery FAILED")).toBeInTheDocument()
    expect(screen.getByText(/失败位置 结果投递/)).toBeInTheDocument()
    expect(screen.getByText("Agent 已完成 · 投递失败")).toBeInTheDocument()
  })

  it("labels unavailable accounting without inventing zero values", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        items: [
          job({
            id: "job-unavailable",
            execution_summary: executionSummary({
              accounting_status: "UNAVAILABLE",
              total_duration_ms: null,
              total_api_duration_ms: null,
              input_tokens: null,
              output_tokens: null,
              cache_creation_input_tokens: null,
              cache_read_input_tokens: null,
              estimated_cost_usd: null,
              models: [],
            }),
          }),
        ],
        page: { limit: 50, has_more: false, next_cursor: null },
      })
    )
    renderRoute("/operations/jobs", "/operations/jobs", <RuntimeRecordsPage />)
    expect(await screen.findByText("统计不可用")).toBeInTheDocument()
    expect(screen.getAllByText(/总耗时 未知/).length).toBeGreaterThan(0)
    expect(screen.queryByText("0 Token")).not.toBeInTheDocument()
  })

  it("labels a cleaned connector as an unavailable historical source", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job({
          source_connector_name: "旧钉钉应用",
          source_connector_availability: "UNAVAILABLE_HISTORICAL",
        }),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        deliveries: { events: [], attempts: [], chunks: [] },
        webhook_events: [],
      })
    )
    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )
    expect(
      await screen.findByText(
        "旧钉钉应用（connector-dingtalk-stream-default） · 不可用历史来源"
      )
    ).toBeInTheDocument()
  })

  it("does not report a completed Agent job as delivered while Delivery is pending", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job(),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        deliveries: {
          events: [deliveryEvent()],
          attempts: [],
          chunks: [],
        },
        webhook_events: [],
      })
    )
    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )
    expect(
      await screen.findByText("Agent 已完成 · 投递待处理")
    ).toBeInTheDocument()
    expect(screen.getByText("投递待处理")).toBeInTheDocument()
    expect(screen.queryByText("Agent 已完成 · 已送达")).not.toBeInTheDocument()
    expect(screen.getByText("尚无投递尝试。")).toBeInTheDocument()
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
    expect(screen.getByText("按渠道会话")).toBeInTheDocument()
    expect(
      screen.getByRole("list", { name: "会话内任务列表" })
    ).toBeInTheDocument()
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
    expect(screen.getByText("2 个")).toBeInTheDocument()
    expect(
      screen.getByText("business_app_publication_with_a_very_long_identifier")
    ).toBeInTheDocument()
  })
})
