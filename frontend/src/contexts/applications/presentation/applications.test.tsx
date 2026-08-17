import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import { ApplicationDetailPage } from "@/contexts/applications/presentation/application-detail-page"
import { ApplicationsPage } from "@/contexts/applications/presentation/applications-page"
import { apiRequest, ApiError } from "@/shared/api/api-client"

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

describe("Business Application workbench", () => {
  it("renders real list data and never falls back to application fixtures", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        items: [
          {
            id: "business_app_test",
            code: "real-app",
            name: "真实诊断应用",
            description: "来自管理 API",
            project_code: "default",
            owner_user_id: "user_admin",
            status: "enabled",
            revision: 3,
            latest_publication_revision: 2,
            active_environments: ["local"],
            runtime_wired: true,
            runtime_status: "partially_wired",
            runtime_environment: "local",
            deployment_environment: "local",
            reason_code: "ready",
            message: "入口已接管，部分策略仅保存",
            runtime_components: {
              trigger_routing: {
                status: "wired",
                reason_code: "ready",
                message: "钉钉入口已接管",
                fields: {},
              },
            },
            affected_routes: [],
            legacy_fallback_enabled: false,
          },
        ],
        runtime_wired: true,
        runtime_status: "partially_wired",
        runtime_environment: "local",
      })
    )
    renderWithQuery(<ApplicationsPage />)
    expect(await screen.findByText("真实诊断应用")).toBeInTheDocument()
    expect(screen.getByText("r3")).toBeInTheDocument()
    expect(screen.getByText("local")).toBeInTheDocument()
    expect(screen.getByLabelText("运行状态：部分接管")).toBeInTheDocument()
    expect(screen.getByText(/1 个应用已接管或部分接管入口/)).toBeInTheDocument()
    expect(screen.queryByText("APP-DEMO-PRIVATE")).not.toBeInTheDocument()
  })

  it("shows a dedicated authentication state on 401", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({ detail: "Authentication required" }, 401)
    )
    renderWithQuery(<ApplicationsPage />)
    expect(await screen.findByText("需要管理会话")).toBeInTheDocument()
    expect(screen.getByText(/通过登录页重新建立会话/)).toBeInTheDocument()
  })

  it("treats a missing runtime state as not wired instead of claiming takeover", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        items: [
          {
            id: "business_app_missing_state",
            code: "missing-state",
            name: "缺失状态应用",
            description: "",
            project_code: "default",
            owner_user_id: "",
            status: "enabled",
            revision: 1,
            active_environments: [],
          },
        ],
      })
    )
    renderWithQuery(<ApplicationsPage />)
    expect(await screen.findByLabelText("运行状态：未接管")).toBeInTheDocument()
    expect(screen.queryByLabelText("运行状态：已接管")).not.toBeInTheDocument()
  })

  it("shows a dedicated authorization state on 403", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({ detail: "Forbidden" }, 403)
    )
    renderWithQuery(<ApplicationsPage />)
    expect(await screen.findByText("没有业务应用权限")).toBeInTheDocument()
    expect(screen.getByText(/business_application\.read/)).toBeInTheDocument()
  })

  it("renders detail and keeps MCP tools as an explicit Agent subset", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/catalog")) {
        return response({
          agents: [],
          workflows: [],
          connectors: [
            {
              id: "connector-dingtalk-stream-default",
              code: "dingtalk-stream-default",
              revision: 3,
              project_code: "",
              status: "enabled",
              config_hash: "",
              runtime_kind: "",
              direction: "ingress",
              component_type: "dingtalk_enterprise_stream",
            },
          ],
          mcp_tools_by_agent_publication: {},
        })
      }
      return response({
        application: {
          id: "business_app_test",
          code: "real-app",
          name: "真实诊断应用",
          description: "来自管理 API",
          project_code: "default",
          owner_user_id: "user_admin",
          status: "enabled",
          revision: 1,
          runtime_wired: false,
          draft: {
            id: "revision_1",
            application_id: "business_app_test",
            revision: 1,
            status: "draft",
            agent_publication_id: "",
            workflow_publication_id: "",
            session_policy: {},
            execution_policy: {},
            validation: { valid: false, errors: [] },
            config_hash: "",
            triggers: [],
            deliveries: [],
            mcp_tools: [],
          },
          publications: [
            {
              id: "business_app_publication_d28011cc1804417e8780a6d1587893b4",
              application_id: "business_app_test",
              revision_id: "revision_1",
              revision: 12,
              schema_version: 1,
              config_hash:
                "eab3972fbb59cfa878ab403632149082cc7f90a46d8405b64f6d463aee72c08f",
              published_by: "user_1354ddf6d1e547faad514fec57a0a3fb",
              published_at: "2026-07-24T16:49:34+08:00",
              runtime_wired: true,
              runtime_status: "partially_wired",
              runtime_environment: "local",
              deployment_environment: "local",
              reason_code: "ready",
              message: "入口已接管",
              runtime_components: {},
              affected_routes: [],
              legacy_fallback_enabled: false,
            },
          ],
          deployments: [],
        },
      })
    })
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <MemoryRouter initialEntries={["/applications/real-app"]}>
          <Routes>
            <Route
              path="/applications/:code"
              element={<ApplicationDetailPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    )
    expect(await screen.findAllByText("真实诊断应用")).not.toHaveLength(0)
    fireEvent.click(screen.getAllByRole("tab", { name: "组成配置" })[0])
    expect(
      await screen.findByText(/请先选择 Agent 发布版本/)
    ).toBeInTheDocument()
    expect(screen.queryByLabelText(/SQL/i)).not.toBeInTheDocument()

    fireEvent.click(screen.getAllByRole("tab", { name: "发布与运行" })[0])
    const publicationCard = await screen.findByTestId(
      "publication-history-card"
    )
    expect(publicationCard).toHaveClass("sm:grid-cols-[minmax(0,1fr)_auto]")
    expect(within(publicationCard).getByText("配置哈希")).toBeInTheDocument()
    expect(within(publicationCard).getByText("发布人")).toBeInTheDocument()
    expect(within(publicationCard).getByText("发布时间")).toBeInTheDocument()
    expect(within(publicationCard).getByText("结构版本")).toBeInTheDocument()
    expect(
      within(publicationCard).getByRole("status").parentElement
    ).toHaveClass("sm:col-span-2")
  })

  it("lists the selected Agent publication MCP tools and saves an explicit subset", async () => {
    let savedBody: Record<string, unknown> | undefined
    const draft = {
      id: "revision_mcp_1",
      application_id: "business_app_mcp",
      revision: 1,
      status: "draft",
      agent_publication_id: "agent_publication_default_v1",
      workflow_publication_id: "",
      session_policy: {
        conversation_mode: "actor",
        recent_message_limit: 20,
        retention_days: 30,
        continuous_conversation_enabled: true,
        attachments_enabled: false,
      },
      execution_policy: {},
      validation: { valid: false, errors: [] },
      config_hash: "",
      triggers: [],
      deliveries: [],
      mcp_tools: [],
    }
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/catalog")) {
        return response({
          agents: [
            {
              id: "agent_publication_default_v1",
              code: "default-diagnostic-agent",
              revision: 29,
              project_code: "default",
              status: "enabled",
              config_hash: "agent-hash",
              runtime_kind: "python-v1",
              direction: "",
              component_type: "agent_publication",
            },
            {
              id: "agent_publication_typescript_v1",
              code: "typescript-diagnostic-agent",
              revision: 1,
              project_code: "default",
              status: "enabled",
              config_hash: "typescript-agent-hash",
              runtime_kind: "typescript-v1",
              direction: "",
              component_type: "agent_publication",
            },
          ],
          workflows: [],
          connectors: [
            {
              id: "connector-dingtalk-stream-default",
              code: "dingtalk-stream-default",
              revision: 3,
              project_code: "",
              status: "enabled",
              config_hash: "",
              runtime_kind: "",
              direction: "ingress",
              component_type: "dingtalk_enterprise_stream",
            },
          ],
          mcp_tools_by_agent_publication: {
            agent_publication_default_v1: [
              {
                server_code: "gitlab-mcp",
                tool_identifier: "search_merge_requests",
                schema_hash: "a".repeat(64),
                description: "只读查询合并请求",
                resource_kind: "gitlab",
              },
              ...[
                "task_workspace_get",
                "task_workspace_list_files",
                "file_get_metadata",
                "file_prepare_materialization",
              ].map((tool_identifier) => ({
                server_code: "file-service",
                tool_identifier,
                schema_hash: "b".repeat(64),
                description: "受治理任务文件工具",
                resource_kind: "file",
              })),
            ],
            agent_publication_typescript_v1: [],
          },
        })
      }
      if (init?.method === "PUT" && url.endsWith("/draft")) {
        savedBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return response({
          revision: {
            ...draft,
            revision: 2,
            mcp_tools: [
              {
                server_code: "gitlab-mcp",
                tool_identifier: "search_merge_requests",
                schema_hash: "a".repeat(64),
              },
            ],
          },
        })
      }
      return response({
        application: {
          id: "business_app_mcp",
          code: "mcp-app",
          name: "MCP 工具配置应用",
          description: "",
          project_code: "default",
          owner_user_id: "user_admin",
          status: "enabled",
          revision: 1,
          draft,
          publications: [],
          deployments: [],
        },
      })
    })

    render(
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: {
              queries: { retry: false },
              mutations: { retry: false },
            },
          })
        }
      >
        <MemoryRouter initialEntries={["/applications/mcp-app"]}>
          <Routes>
            <Route
              path="/applications/:code"
              element={<ApplicationDetailPage />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(await screen.findByText("MCP 工具配置应用")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("tab", { name: "组成配置" }))
    const conversationMode = (await screen.findByLabelText(
      "会话范围"
    )) as HTMLSelectElement
    expect(conversationMode).toHaveValue("channel")
    expect(within(conversationMode).getAllByRole("option")).toHaveLength(1)
    expect(
      within(conversationMode).getByRole("option", {
        name: "按渠道、发布版本与数据范围隔离",
      })
    ).toBeInTheDocument()
    const agentSelector = screen.getByRole("combobox", {
      name: "Agent 发布版本",
    })
    expect(
      await within(agentSelector).findByRole("option", {
        name: "default-diagnostic-agent · r29 · Python Runtime",
      })
    ).toBeInTheDocument()
    expect(
      within(agentSelector).queryByRole("option", {
        name: /typescript-diagnostic-agent/,
      })
    ).not.toBeInTheDocument()
    expect(screen.queryByText("操作失败，请重试。")).not.toBeInTheDocument()
    const continuousConversation = screen.getByLabelText("连续会话")
    expect(continuousConversation).toBeChecked()
    const attachments = screen.getByLabelText("允许消息附件")
    expect(attachments).not.toBeChecked()
    fireEvent.click(screen.getByRole("checkbox", { name: "任务工作区" }))
    expect(attachments).toBeChecked()
    expect(attachments).toHaveAttribute("aria-disabled", "true")
    expect(continuousConversation).toBeChecked()
    expect(continuousConversation).toHaveAttribute("aria-disabled", "true")
    const mcpTool = await screen.findByLabelText(
      "选择 MCP Tool search_merge_requests"
    )
    fireEvent.click(mcpTool)
    expect(mcpTool).toBeChecked()
    fireEvent.click(screen.getByRole("checkbox", { name: "File MCP" }))
    const requiredFileTool = screen.getByLabelText(
      "选择 MCP Tool file_prepare_materialization"
    )
    expect(requiredFileTool).toBeChecked()
    expect(requiredFileTool).toHaveAttribute("aria-disabled", "true")
    fireEvent.click(screen.getByRole("button", { name: "保存新草稿" }))

    await waitFor(() =>
      expect(savedBody).toMatchObject({
        session_policy: {
          conversation_mode: "channel",
          continuous_conversation_enabled: true,
          attachments_enabled: true,
        },
        mcp_tools: expect.arrayContaining([
          "search_merge_requests",
          "task_workspace_get",
          "task_workspace_list_files",
          "file_get_metadata",
          "file_prepare_materialization",
        ]),
      })
    )
  })

  it("injects CSRF for writes and exposes stable conflict metadata", async () => {
    document.cookie = "enterprise_agent_csrf=csrf-value"
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response(
        {
          detail: {
            code: "revision_conflict",
            message: "changed",
            field_errors: [],
            current_revision: 7,
          },
        },
        409
      )
    )
    await expect(
      apiRequest("/api/admin/business-applications/real-app", {
        method: "PUT",
        body: { expected_revision: 1 },
      })
    ).rejects.toMatchObject({
      status: 409,
      code: "revision_conflict",
      currentRevision: 7,
    } satisfies Partial<ApiError>)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const init = fetch.mock.calls[0][1]
    expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf-value")
    expect(init?.credentials).toBe("include")
  })

  it("preserves governed nested error codes and safe messages", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response(
        {
          detail: {
            error: {
              code: "mcp_resource_publish_revision_conflict",
              message: "发布请求与既有幂等记录冲突",
              correlation_id: "correlation-safe",
              retryable: false,
            },
          },
        },
        409
      )
    )

    await expect(
      apiRequest("/api/platform/resources/resource-test/publish")
    ).rejects.toMatchObject({
      status: 409,
      code: "mcp_resource_publish_revision_conflict",
      message: "发布请求与既有幂等记录冲突",
    } satisfies Partial<ApiError>)
  })

  it("does not expose an English server error to users", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({ detail: "Internal server error" }, 500)
    )

    await expect(apiRequest("/api/admin/test")).rejects.toMatchObject({
      status: 500,
      message: "服务器内部错误，请稍后重试。",
    } satisfies Partial<ApiError>)
  })
})
