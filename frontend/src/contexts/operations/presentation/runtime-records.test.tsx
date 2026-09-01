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
    internal_user_id: "user-1",
    user_username: "admin",
    user_display_name: "Administrator",
    project_code: "default",
    source_channel: "dingding_stream",
    source_connector_id: "connector-dingtalk-stream-default",
    agent_code: "default-diagnostic-agent",
    correlation_id: "correlation-1",
    business_application_id: "application-1",
    business_application_code: "diagnostic-app",
    business_application_name: "生产诊断助手",
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
    tool_contract: toolContractSummary(),
    created_at: "2026-07-24T10:00:00+00:00",
    ...overrides,
  }
}

function toolContractSummary(overrides: Record<string, unknown> = {}) {
  return {
    status: "MATCH",
    last_invocation_id: "invocation-2",
    observation_hash: "a".repeat(64),
    prompt_template_version: "agent-system-prompt-v2",
    prompt_contract_hash: "b".repeat(64),
    component_build_identities: [
      {
        component: "control-plane",
        source_revision: "revision-1",
        build_id: "build-1",
        platform: "linux/amd64",
      },
    ],
    ...overrides,
  }
}

function toolContractEvidence() {
  const identity = {
    source_revision: "revision-1",
    build_id: "build-1",
    platform: "linux/amd64",
  }
  const frozen = {
    server_code: "file-service",
    tool_name: "file_create_commit_intent",
    schema_hash: "c".repeat(64),
  }
  const observation = (status: "MATCH" | "DRIFT", index: number) => ({
    invocation_id: `invocation-${index}`,
    request_digest: String(index).repeat(64),
    sequence: 2,
    created_at: `2026-07-24T10:00:0${index}+00:00`,
    status,
    observation_hash: String(index + 2).repeat(64),
    snapshot_hash: "d".repeat(64),
    component_build_identities: [
      { component: "control-plane", ...identity },
      { component: "agent-worker", ...identity },
      { component: "python-runtime", ...identity },
      {
        component: "file-service",
        ...identity,
        image_digest: `sha256:${"e".repeat(64)}`,
      },
    ],
    job_frozen: [frozen],
    file_mcp_live: {
      status: "OBSERVED",
      toolset_hash: "f".repeat(64),
      build_identity: { component: "file-service", ...identity },
      tools:
        status === "DRIFT"
          ? [
              {
                server_code: "file-service",
                tool_name: "file_retain_version",
                schema_hash: "9".repeat(64),
                status: "EXTRA_REMOTE_IGNORED",
              },
            ]
          : [
              { ...frozen, status: "MATCH" },
              {
                server_code: "file-service",
                tool_name: "file_retain_version",
                schema_hash: "9".repeat(64),
                status: "EXTRA_REMOTE_IGNORED",
              },
            ],
    },
    runtime_effective:
      status === "DRIFT"
        ? []
        : [
            {
              ...frozen,
              sdk_tool_name: "mcp__file_service__file_create_commit_intent",
              origin: "frozen_mcp",
              authorization_status: "ALLOWED",
            },
            {
              server_code: "file-service",
              tool_name: "select_sandbox_output",
              sdk_tool_name: "mcp__file_service__select_sandbox_output",
              origin: "runtime_derived",
              schema_hash: "8".repeat(64),
              authorization_status: "ALLOWED",
              dependency_tool_name: "file_create_commit_intent",
            },
          ],
    prompt: {
      template_version: "agent-system-prompt-v2",
      contract_hash: "b".repeat(64),
      declared_tools:
        status === "DRIFT"
          ? []
          : [
              "mcp__file_service__file_create_commit_intent",
              "mcp__file_service__select_sandbox_output",
            ],
    },
    matrix: [
      {
        server_code: "file-service",
        tool_name: "file_create_commit_intent",
        status: status === "DRIFT" ? "MISSING_REMOTE" : "MATCH",
      },
      {
        server_code: "file-service",
        tool_name: "file_retain_version",
        status: "EXTRA_REMOTE_IGNORED",
      },
      ...(status === "MATCH"
        ? [
            {
              server_code: "file-service",
              tool_name: "select_sandbox_output",
              status: "RUNTIME_DERIVED",
            },
          ]
        : []),
    ],
  })
  return {
    summary: toolContractSummary({ status: "DRIFT" }),
    snapshot: {
      id: "snapshot-1",
      schema_version: 1,
      snapshot_hash: "d".repeat(64),
      created_at: "2026-07-24T10:00:00+00:00",
      tools: [frozen],
    },
    observations: [observation("DRIFT", 1), observation("MATCH", 2)],
    notice: "工具契约状态来自该 Job 的冻结快照与不可变 Runtime 事件。",
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
    source_protocol_version: "1.3",
    ...overrides,
  }
}

function fileOperations(overrides: Record<string, unknown> = {}) {
  return {
    file_service: { configured: true, ready: true, reason_code: "ready" },
    file_worker: {
      configured: true,
      ready: true,
      reason_code: "ready",
      attachment_queue: {
        availability: "available",
        ready: 0,
        unacked: 0,
        consumers: 1,
      },
    },
    document_processing: {
      configured: true,
      ready: true,
      reason_code: "ready",
      file_processing_worker: {
        configured: true,
        ready: true,
        reason_code: "ready",
        components: {
          rabbitmq: "ready",
          file_service: "ready",
          docling: "ready",
        },
      },
      queues: {
        processing: {
          availability: "available",
          ready: 2,
          unacked: 1,
          consumers: 1,
        },
        retry: {
          availability: "available",
          ready: 3,
          unacked: 0,
          consumers: 0,
        },
        dead: {
          availability: "available",
          ready: 4,
          unacked: 0,
          consumers: 0,
        },
      },
      operations: {
        groups: [
          {
            tenant_id: "tenant-safe",
            application_id: "application-safe",
            application_code: "diagnostic-safe",
            publication_id: "publication-safe",
            profile_code: "docling-layout-ocr-v2",
            status: "FAILED",
            count: 1,
            total_attempts: 2,
            source_size_bytes: 2048,
            output_size_bytes: 0,
            earliest_created_at: "2026-08-15T00:00:00+00:00",
            latest_updated_at: "2026-08-15T01:00:00+00:00",
          },
        ],
        recent_failures: [
          {
            run_id: "run-safe",
            source_version_id: "version-safe",
            tenant_id: "tenant-safe",
            job_id: "job-safe",
            application_id: "application-safe",
            application_code: "diagnostic-safe",
            publication_id: "publication-safe",
            profile_code: "docling-layout-ocr-v2",
            profile_hash: "a".repeat(64),
            status: "FAILED",
            attempt: 2,
            error_code: "docling_format_rejected",
            page_count: null,
            processing_time_ms: 100,
            updated_at: "2026-08-15T01:00:00+00:00",
          },
        ],
        traces: [
          {
            run_id: "run-safe",
            source_version_id: "version-safe",
            tenant_id: "tenant-safe",
            job_id: "job-safe",
            application_id: "application-safe",
            application_code: "diagnostic-safe",
            publication_id: "publication-safe",
            profile_code: "docling-layout-ocr-v2",
            profile_hash: "a".repeat(64),
            status: "FAILED",
            attempt: 2,
            error_code: "docling_format_rejected",
            page_count: null,
            processing_time_ms: 100,
            updated_at: "2026-08-15T01:00:00+00:00",
            processor_code: "docling-serve",
            processor_version: "1.30.0",
            processor_build_digest: `sha256:${"b".repeat(64)}`,
            source_size_bytes: 2048,
            created_at: "2026-08-15T00:00:00+00:00",
            representations: [
              {
                representation_id: "representation-safe",
                source_version_id: "version-safe",
                kind: "MARKDOWN",
                media_type: "text/markdown",
                status: "AVAILABLE",
                size_bytes: 100,
                content_sha256: "c".repeat(64),
                profile_hash: "a".repeat(64),
                created_at: "2026-08-15T00:30:00+00:00",
                content_deleted_at: "",
              },
            ],
          },
        ],
      },
    },
    backlog: {
      cleanup: 0,
      staging: 0,
      attachment: 0,
      workspace: 0,
      retained: 0,
      conflict: 0,
      domain_outbox: 0,
    },
    earliest_due: "",
    domain_outbox_earliest_created_at: "",
    domain_outbox_failure_code: "",
    recent_cleanup: null,
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

function runAudit(overrides: Record<string, unknown> = {}) {
  return {
    id: "audit-1",
    job_id: "job-1",
    invocation_id: "invocation-1",
    request_digest: "a".repeat(64),
    attempt_no: 1,
    status: "SUCCEEDED",
    audit_sha256: "b".repeat(64),
    context_manifest: {
      sources: ["system_prompt", "session", "file_workspace"],
      estimated_characters: 4096,
    },
    system_prompt: "完整 System Prompt 内容",
    user_prompt: "完整会话正文与文件内容",
    tool_definitions: [{ name: "mcp__file__read", input_schema: {} }],
    permission_snapshot: { allowed_tools: ["mcp__file__read"] },
    init_snapshot: { tools: ["mcp__file__read"] },
    sdk_messages: [{ type: "assistant", content: "模型原始响应全文" }],
    api_requests: [{ body: { system: "完整 System Prompt 内容" } }],
    api_responses: [{ body: { content: "模型原始响应全文" } }],
    tool_executions: [
      {
        tool_name: "mcp__file__read",
        input: { path: "example.md" },
        output: "工具结果原文",
      },
    ],
    model_requests: [{ sequence: 1, context_tokens: 144 }],
    usage: { input_tokens: 120, output_tokens: 32 },
    summary: {
      model_request_count: 1,
      max_request_context_tokens: 144,
      cumulative_input_tokens: 120,
      cumulative_output_tokens: 32,
      cache_creation_input_tokens: 8,
      cache_read_input_tokens: 16,
      total_cost_usd: 0.012345,
      registered_tool_count: 9,
      max_loaded_tool_count: 4,
      auto_approved_tool_count: 0,
      tool_call_count: 1,
      distinct_tool_count: 1,
    },
    raw_api_capture_status: "captured",
    provider_thinking_disclosure: "仅展示上游 SDK/API 实际返回的可观测内容。",
    error: {},
    started_at: "2026-07-24T10:00:00+00:00",
    finished_at: "2026-07-24T10:00:01+00:00",
    created_at: "2026-07-24T10:00:01+00:00",
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
  it("shows live document processing dependencies and queue state", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input).startsWith("/api/admin/file-operations")) {
        return response(fileOperations())
      }
      return response({
        items: [],
        page: { limit: 50, has_more: false, next_cursor: null },
      })
    })

    renderRoute("/operations/jobs", "/operations/jobs", <RuntimeRecordsPage />)

    expect(await screen.findByText(/文档解析\/OCR 就绪/)).toBeInTheDocument()
    expect(screen.getByText("文档处理队列")).toBeInTheDocument()
    expect(
      screen.getByText(/ready 2 · unacked 1 · consumer 1/)
    ).toBeInTheDocument()
    expect(screen.getByText(/retry 3 · dead 4/)).toBeInTheDocument()
    expect(screen.getByText(/Docling 就绪/)).toBeInTheDocument()
    expect(screen.getByText("处理分组")).toBeInTheDocument()
    expect(
      screen.getByText(/diagnostic-safe · docling-layout-ocr-v2 · FAILED/)
    ).toBeInTheDocument()
    expect(screen.getByText("最近失败")).toBeInTheDocument()
    expect(screen.getByText(/docling_format_rejected/)).toBeInTheDocument()
    expect(
      screen.getByText("source → run → representation → Job")
    ).toBeInTheDocument()
    expect(screen.getByText(/run-safe → 1 representation/)).toBeInTheDocument()
  })

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
            tool_contract: toolContractSummary({
              status: "NOT_OBSERVED",
              last_invocation_id: "",
              observation_hash: "",
              prompt_template_version: "",
              prompt_contract_hash: "",
              component_build_identities: [],
            }),
          }),
        ],
        page: { limit: 50, has_more: false, next_cursor: null },
      })
    )
    renderRoute("/operations/jobs", "/operations/jobs", <RuntimeRecordsPage />)
    expect(
      (await screen.findAllByText(/Administrator（@admin）/)).length
    ).toBeGreaterThan(0)
    expect(
      screen.getByText("生产诊断助手（diagnostic-app）")
    ).toBeInTheDocument()
    expect(
      screen.getByText("历史兼容任务（无业务应用归因）")
    ).toBeInTheDocument()
    expect(screen.getAllByText("legacy_unattributed").length).toBeGreaterThan(0)
    expect(screen.getAllByText(/总耗时 2.40 秒/).length).toBeGreaterThan(0)
    expect(screen.getAllByText("claude-safe-model").length).toBeGreaterThan(0)
    expect(screen.getAllByText("MATCH").length).toBeGreaterThan(0)
    expect(screen.getByText("NOT_OBSERVED（不等于健康）")).toBeInTheDocument()
  })

  it("filters jobs by local time, username and application name", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        items: [],
        page: { limit: 50, has_more: false, next_cursor: null },
      })
    )
    renderRoute("/operations/jobs", "/operations/jobs", <RuntimeRecordsPage />)
    await screen.findByText("当前时间窗口没有任务。")
    const initialParams = new URL(
      String(
        fetchMock.mock.calls.find(([url]) =>
          String(url).startsWith("/api/admin/jobs?")
        )?.[0]
      ),
      "http://localhost"
    ).searchParams
    expect(
      new Date(String(initialParams.get("end"))).getTime() -
        new Date(String(initialParams.get("start"))).getTime()
    ).toBe(24 * 60 * 60 * 1000)

    fireEvent.change(screen.getByLabelText("开始时间"), {
      target: { value: "2026-08-13T09:00" },
    })
    fireEvent.change(screen.getByLabelText("结束时间"), {
      target: { value: "2026-08-13T10:00" },
    })
    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "admin" },
    })
    fireEvent.change(screen.getByLabelText("应用名"), {
      target: { value: "诊断助手" },
    })
    fireEvent.click(screen.getByRole("button", { name: "应用筛选" }))

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([url]) =>
          String(url).startsWith("/api/admin/jobs?")
        )
      ).toHaveLength(2)
    )
    const requestUrl = String(
      fetchMock.mock.calls
        .filter(([url]) => String(url).startsWith("/api/admin/jobs?"))
        .at(-1)?.[0]
    )
    const params = new URL(requestUrl, "http://localhost").searchParams
    expect(params.get("username")).toBe("admin")
    expect(params.get("application_name")).toBe("诊断助手")
    expect(params.get("start")).toBe(new Date("2026-08-13T09:00").toISOString())
    expect(params.get("end")).toBe(new Date("2026-08-13T10:00").toISOString())
    expect(screen.queryByLabelText("用户安全标识")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Agent")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("模型")).not.toBeInTheDocument()
  })

  it("shows immutable application provenance in job detail", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job(),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        execution_summary: executionSummary({
          observed_model_turn_count: 2,
          runtime_invocation_count: 1,
        }),
        model_calls: {
          items: [modelCall()],
          limit: 50,
          has_more: false,
          next_cursor: null,
        },
        run_audits: [runAudit()],
        file_workspace: {
          enabled: true,
          manifest_schema_version: 5,
          policy_source: "job_file_manifest",
          formats: [
            {
              format_code: "LOG",
              file_count: 1,
              allowed_actions: ["MATERIALIZE", "DELIVER"],
            },
            {
              format_code: "MARKDOWN",
              file_count: 1,
              allowed_actions: ["MATERIALIZE", "EDIT", "COMMIT", "DELIVER"],
            },
          ],
          output_commits: [
            {
              format_code: "MARKDOWN",
              status: "COMMITTED",
              commit_count: 1,
            },
          ],
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
    expect(screen.getByText("模型轮次 / Runtime 调用")).toBeInTheDocument()
    expect(screen.getByText("2 次 / 1 次")).toBeInTheDocument()
    expect(screen.getByText(/Manifest v5/)).toBeInTheDocument()
    expect(screen.getByText("只读并发送既有精确版本")).toBeInTheDocument()
    expect(screen.getByText(/不渲染正文/)).toBeInTheDocument()
    expect(screen.getByText("本 Job 输出提交")).toBeInTheDocument()
    expect(screen.getByText(/· 1 个 · COMMITTED/)).toBeInTheDocument()
    expect(screen.getByText(/不回写输入/)).toBeInTheDocument()
    expect(screen.getByText("上下文与原始运行审计")).toBeInTheDocument()
    expect(screen.getByText("峰值请求上下文")).toBeInTheDocument()
    expect(screen.getByText("144 tokens")).toBeInTheDocument()
    const contextDisclosure = screen
      .getByText("完整上下文与 Prompt")
      .closest("details")
    expect(contextDisclosure).not.toHaveAttribute("open")
    fireEvent.click(screen.getByText("完整上下文与 Prompt"))
    expect(contextDisclosure).toHaveAttribute("open")
    expect(screen.getByText("完整 System Prompt 内容")).toHaveClass(
      "max-h-[32rem]",
      "overflow-auto"
    )
    expect(screen.getAllByText("模型请求与原始响应")).toHaveLength(1)
    expect(screen.getAllByText("工具定义、权限与执行原文")).toHaveLength(1)
    expect(screen.getAllByText("Token、成本与审计元数据")).toHaveLength(1)
  })

  it("shows immutable per-invocation Tool contract layers and drift history", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job({ tool_contract: toolContractSummary({ status: "DRIFT" }) }),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        execution_summary: executionSummary(),
        model_calls: {
          items: [],
          limit: 50,
          has_more: false,
          next_cursor: null,
        },
        file_workspace: {
          enabled: false,
          manifest_schema_version: null,
          formats: [],
          output_commits: [],
        },
        tool_contract: toolContractEvidence(),
        deliveries: { events: [], attempts: [], chunks: [] },
        webhook_events: [],
      })
    )

    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )

    expect(await screen.findByText("工具契约对账")).toBeInTheDocument()
    const toolContractPanel = screen.getByTestId("tool-contract-panel")
    const lastInvocationLabel = screen.getByText("最后观测 Invocation")
    expect(lastInvocationLabel).toBeVisible()
    const lastInvocationMetric = lastInvocationLabel.closest("div")
    expect(lastInvocationMetric).toHaveClass("min-w-0")
    expect(lastInvocationMetric?.querySelector("dd")).toHaveClass(
      "min-w-0",
      "[overflow-wrap:anywhere]"
    )
    expect(
      screen.getByText(
        "工具契约状态来自该 Job 的冻结快照与不可变 Runtime 事件。"
      )
    ).toBeVisible()
    const toolContractDisclosures =
      toolContractPanel.querySelectorAll("details")
    expect(toolContractDisclosures).toHaveLength(13)
    expect(
      Array.from(toolContractDisclosures).every((item) => !item.open)
    ).toBe(true)
    expect(screen.getAllByText("DRIFT").length).toBeGreaterThan(0)
    const snapshotDisclosure = screen
      .getByText("Job Frozen Snapshot")
      .closest("details")
    fireEvent.click(screen.getByText("Job Frozen Snapshot"))
    expect(snapshotDisclosure).toHaveAttribute("open")
    const firstLayerDisclosure = screen
      .getAllByText("A. Job frozen")[0]
      .closest("details")
    fireEvent.click(screen.getAllByText("A. Job frozen")[0])
    expect(firstLayerDisclosure).toHaveAttribute("open")
    expect(screen.getAllByText("A. Job frozen")).toHaveLength(2)
    expect(screen.getAllByText("B. File MCP live")).toHaveLength(2)
    expect(screen.getAllByText("C. Runtime effective")).toHaveLength(2)
    expect(screen.getAllByText("D. Prompt declaration")).toHaveLength(2)
    expect(screen.getAllByText("EXTRA_REMOTE_IGNORED").length).toBeGreaterThan(
      0
    )
    expect(screen.getByText("RUNTIME_DERIVED")).toBeInTheDocument()
    expect(screen.getByText(/Runtime 派生 · ALLOWED/)).toBeInTheDocument()
    expect(screen.getAllByText("control-plane")).toHaveLength(2)
    expect(screen.getAllByText("python-runtime")).toHaveLength(2)
    expect(
      screen.getAllByRole("button", { name: /复制/ }).length
    ).toBeGreaterThan(0)
    expect(screen.queryByText(/raw-provider-secret/)).not.toBeInTheDocument()
  })

  it("aggregates multiple runtime attempts while keeping every body group closed", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job(),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        execution_summary: executionSummary(),
        model_calls: {
          items: [],
          limit: 50,
          has_more: false,
          next_cursor: null,
        },
        run_audits: [
          runAudit(),
          runAudit({
            id: "audit-2",
            invocation_id: "invocation-2",
            attempt_no: 2,
            status: "FAILED",
            summary: {
              model_request_count: 2,
              max_request_context_tokens: 200,
              cumulative_input_tokens: 80,
              cumulative_output_tokens: 10,
              cache_creation_input_tokens: 2,
              cache_read_input_tokens: 4,
              total_cost_usd: 0.01,
              registered_tool_count: 12,
              max_loaded_tool_count: 6,
              auto_approved_tool_count: 0,
              tool_call_count: 2,
              distinct_tool_count: 2,
            },
          }),
        ],
        deliveries: { events: [], attempts: [], chunks: [] },
        webhook_events: [],
      })
    )

    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )

    expect(await screen.findByText("200 tokens")).toBeInTheDocument()
    expect(screen.getAllByText("完整上下文与 Prompt")).toHaveLength(2)
    const disclosures = document.querySelectorAll("details")
    expect(disclosures).toHaveLength(9)
    expect(Array.from(disclosures).every((item) => !item.open)).toBe(true)
  })

  it("states that historical NOT_OBSERVED is not a health result", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job({
          tool_contract: toolContractSummary({
            status: "NOT_OBSERVED",
            last_invocation_id: "",
            observation_hash: "",
            prompt_template_version: "",
            prompt_contract_hash: "",
            component_build_identities: [],
          }),
        }),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        execution_summary: executionSummary({ source_protocol_version: "1.3" }),
        model_calls: {
          items: [],
          limit: 50,
          has_more: false,
          next_cursor: null,
        },
        file_workspace: {
          enabled: false,
          manifest_schema_version: null,
          formats: [],
          output_commits: [],
        },
        tool_contract: {
          summary: toolContractSummary({
            status: "NOT_OBSERVED",
            last_invocation_id: "",
            observation_hash: "",
            prompt_template_version: "",
            prompt_contract_hash: "",
            component_build_identities: [],
          }),
          snapshot: null,
          observations: [],
          notice:
            "历史 protocol 1.3 Job 未记录工具契约；NOT_OBSERVED 不代表健康。",
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

    expect(
      await screen.findByText(
        "历史 protocol 1.3 Job 未记录工具契约；NOT_OBSERVED 不代表健康。"
      )
    ).toBeInTheDocument()
    expect(
      screen.getAllByText("NOT_OBSERVED（不等于健康）").length
    ).toBeGreaterThan(0)
    expect(
      screen.getByText(/此历史 Job 没有上下文审计记录/)
    ).toBeInTheDocument()
  })

  it("renders document source formats in job evidence instead of failing closed to fixture copy", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job(),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        execution_summary: executionSummary(),
        model_calls: {
          items: [],
          limit: 50,
          has_more: false,
          next_cursor: null,
        },
        file_workspace: {
          enabled: true,
          manifest_schema_version: 5,
          policy_source: "job_file_manifest",
          formats: [
            {
              format_code: "PNG",
              file_count: 4,
              allowed_actions: ["READ_METADATA", "RETAIN", "DELIVER"],
            },
            {
              format_code: "DOCX",
              file_count: 3,
              allowed_actions: ["READ_METADATA", "RETAIN", "DELIVER"],
            },
            {
              format_code: "MARKDOWN",
              file_count: 2,
              allowed_actions: ["MATERIALIZE"],
            },
          ],
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
    expect(screen.queryByText("管理服务不可用")).not.toBeInTheDocument()
    expect(screen.getByText("PNG")).toBeInTheDocument()
    expect(screen.getByText("DOCX")).toBeInTheDocument()
    expect(screen.getByText(/输入 Manifest 4 个文件/)).toBeInTheDocument()
    expect(screen.getAllByText(/原件不进沙盒/).length).toBeGreaterThan(0)
  })

  it("does not reuse fixture copy when job evidence cannot be parsed", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: { id: "job-1" },
        session_ref: { id: "session-1" },
        deliveries: { events: [], attempts: [], chunks: [] },
      })
    )
    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )
    expect(await screen.findByText("管理服务不可用")).toBeInTheDocument()
    expect(
      screen.getByText("任务证据无法展示。控制面返回了当前页面尚未识别的字段。")
    ).toBeInTheDocument()
    expect(
      screen.queryByText("无法读取真实控制面数据。页面不会回退到静态 fixture。")
    ).not.toBeInTheDocument()
  })

  it("renders only whitelisted metadata from a structured tool summary", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job({ tool_call_count: 1 }),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [
          {
            id: "tool-call-1",
            tool_name: "ones_work_item_search",
            status: "SUCCEEDED",
            response_summary: {
              items: [{ name: "must-not-render" }],
              total: 1,
              truncated: false,
              untrusted_data: true,
            },
          },
        ],
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
      await screen.findByText("返回 1 项 · 未截断 · 含外部不受信任数据")
    ).toBeInTheDocument()
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument()
    expect(screen.queryByText("must-not-render")).not.toBeInTheDocument()
  })

  it("loads the next model-call page without replacing prior rows", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input) => {
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

    fireEvent.click(
      await screen.findByRole("button", { name: "加载更多模型请求" })
    )

    expect(
      await screen.findByText("claude-safe-model-next")
    ).toBeInTheDocument()
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
      expect(
        screen.getByText("Job 重试已耗尽", { exact: false })
      ).toBeInTheDocument()
      expect(
        screen.getByText("不可用（SDK 未提供请求起点）")
      ).toBeInTheDocument()
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
        model_calls: {
          items: [],
          limit: 50,
          has_more: false,
          next_cursor: null,
        },
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

    expect(
      await screen.findByText("Agent 执行 SUCCEEDED · Delivery FAILED")
    ).toBeInTheDocument()
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

  it("renders the one-based Delivery chunk position without incrementing it", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        job: job(),
        session_ref: { id: "session-1" },
        steps: [],
        tool_calls: [],
        deliveries: {
          events: [
            deliveryEvent({
              status: "SUCCEEDED",
              attempt_count: 1,
              terminal: true,
              delivered: true,
            }),
          ],
          attempts: [
            {
              id: "attempt-1",
              job_id: "job-1",
              delivery_outbox_id: "delivery-1",
              replay_no: 0,
              attempt_no: 1,
              route_type: "dingtalk_private",
              connector_id: "connector-dingtalk-stream-default",
              target_summary: {},
              correlation_id: "correlation-1",
              status: "SUCCEEDED",
              error_code: "",
              error_message: null,
              created_at: "2026-07-24T10:00:11+00:00",
              finished_at: "2026-07-24T10:00:12+00:00",
            },
          ],
          chunks: [
            {
              id: "chunk-1",
              attempt_id: "attempt-1",
              delivery_outbox_id: "delivery-1",
              replay_no: 0,
              attempt_no: 1,
              chunk_index: 1,
              chunk_count: 1,
              status: "SUCCEEDED",
              payload_summary: {},
              error_message: null,
              created_at: "2026-07-24T10:00:11+00:00",
              sent_at: "2026-07-24T10:00:12+00:00",
            },
          ],
        },
        webhook_events: [],
      })
    )
    renderRoute(
      "/operations/jobs/job-1",
      "/operations/jobs/:jobId",
      <RuntimeJobDetailPage />
    )

    expect(await screen.findByText("分片 1/1 · 已送达")).toBeInTheDocument()
    expect(screen.queryByText("分片 2/1 · 已送达")).not.toBeInTheDocument()
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
