import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
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
    </QueryClientProvider>,
  )
}

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
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
            active_environments: ["test"],
            runtime_wired: false,
          },
        ],
        runtime_wired: false,
      }),
    )
    renderWithQuery(<ApplicationsPage />)
    expect(await screen.findByText("真实诊断应用")).toBeInTheDocument()
    expect(screen.getByText("r3")).toBeInTheDocument()
    expect(screen.getByText("test")).toBeInTheDocument()
    expect(screen.getByText("runtime_wired=false：")).toBeInTheDocument()
    expect(screen.queryByText("APP-DEMO-PRIVATE")).not.toBeInTheDocument()
  })

  it("shows a dedicated authentication state on 401", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({ detail: "Authentication required" }, 401),
    )
    renderWithQuery(<ApplicationsPage />)
    expect(await screen.findByText("需要管理会话")).toBeInTheDocument()
    expect(screen.getByText(/通过登录页重新建立会话/)).toBeInTheDocument()
  })

  it("shows a dedicated authorization state on 403", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({ detail: "Forbidden" }, 403),
    )
    renderWithQuery(<ApplicationsPage />)
    expect(await screen.findByText("没有业务应用权限")).toBeInTheDocument()
    expect(screen.getByText(/business_application\.read/)).toBeInTheDocument()
  })

  it("renders detail and keeps capabilities as governed empty state", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/catalog")) {
        return response({
          agents: [],
          workflows: [],
          connectors: [],
          capabilities: [],
          capability_catalog_connected: false,
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
          capability_catalog_connected: false,
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
            capabilities: [],
          },
          publications: [],
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
      </QueryClientProvider>,
    )
    expect(await screen.findAllByText("真实诊断应用")).not.toHaveLength(0)
    fireEvent.click(screen.getAllByRole("tab", { name: "组成配置" })[0])
    expect(
      await screen.findByText(/Capability Catalog 尚未接入/),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText(/SQL/i)).not.toBeInTheDocument()
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
        409,
      ),
    )
    await expect(
      apiRequest("/api/admin/business-applications/real-app", {
        method: "PUT",
        body: { expected_revision: 1 },
      }),
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
})
