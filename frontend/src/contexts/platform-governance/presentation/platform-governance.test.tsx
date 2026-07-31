import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import { createDebugJob } from "@/contexts/operations/infrastructure/debug-job-api"
import { DebugJobPage } from "@/contexts/operations/presentation/debug-job-page"
import { createGovernedResource } from "@/contexts/platform-governance/infrastructure/platform-governance-api"
import { CredentialCenterPage } from "@/contexts/platform-governance/presentation/credential-center-page"
import { ToolResourcesPage } from "@/contexts/platform-governance/presentation/tool-resources-page"
import { navigationGroups } from "@/mocks/dashboard"

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

function renderWithQuery(ui: React.ReactNode) {
  return render(
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
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

const platformSecret = {
  id: "secret-oracle",
  code: "oracle_reader_password",
  provider: "encrypted_db",
  secret_ref: "secret://platform/oracle_reader_password",
  purpose: "Oracle 只读账号密码",
  status: "enabled",
  active_version: 1,
  configured: true,
  masked_summary: "configured",
  revision: 1,
  updated_at: "2026-07-29T00:00:00Z",
}

function governedOracleResource() {
  return {
    id: "resource-oracle",
    code: "oracle_orders",
    name: "Oracle 订单库",
    resource_kind: "database",
    scope_type: "base",
    environment_code: "local",
    base_code: "base-one",
    workshop_code: null,
    status: "enabled",
    draft: {
      id: "draft-oracle",
      resource_id: "resource-oracle",
      draft_revision: 1,
      provider_type: "oracle",
      config: {
        host: "oracle.example.internal",
        port: 1521,
        service_name: "ORCL",
        username: "reader",
        schema: "ORDERS",
      },
      secret_refs: {
        password_ref: "secret://platform/oracle_reader_password",
      },
      status: "DRAFT",
      updated_at: "2026-07-29T00:00:00Z",
    },
    published_revision: null,
    effective_revision_id: "",
    activation_status: "EMPTY",
    last_known_good_generation_id: "",
    safe_error_summary: "",
    affected_applications: [],
  }
}

describe("Phase 5 platform governance UI", () => {
  it("exposes governance navigation with separate resources and credential center", () => {
    const group = navigationGroups.find((item) => item.label === "平台治理")
    expect(group?.items.map((item) => item.href)).toEqual([
      "/platform/api-capabilities",
      "/platform/resources",
      "/platform/secrets",
    ])
    expect(group?.items.map((item) => item.requiredCapability)).toEqual([
      "api_capabilities.read",
      "platform.read",
      "secrets.read",
    ])
  })

  it("renders credential metadata and never offers Master Key or reserved providers", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({ secrets: [platformSecret] })
    )
    renderWithQuery(<CredentialCenterPage />)

    expect(
      await screen.findByText("oracle_reader_password")
    ).toBeInTheDocument()
    expect(
      screen.getByText("secret://platform/oracle_reader_password")
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Secret 明文")).toHaveAttribute(
      "type",
      "password"
    )
    expect(screen.queryByLabelText(/Master Key/i)).not.toBeInTheDocument()
    expect(
      screen.queryByRole("option", { name: /Vault|KMS/ })
    ).not.toBeInTheDocument()
  })

  it("renders actionable Secret dependency metadata", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/usage")) {
        return response({
          usage: {
            secret: platformSecret,
            usage_count: 1,
            active_usage_count: 1,
            dependencies: [
              {
                dependency_type: "runtime_config",
                id: "runtime-secret-one",
                code: "ANTHROPIC_API_KEY",
                status: "enabled",
                active: true,
                field_paths: ["secret_ref"],
                metadata: {
                  scope_type: "global",
                  scope_code: "global",
                  service_name: "agent-worker",
                },
              },
            ],
          },
        })
      }
      return response({ secrets: [platformSecret] })
    })
    renderWithQuery(<CredentialCenterPage />)

    expect(
      await screen.findByText("oracle_reader_password")
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "查看引用" }))

    expect(
      await screen.findByText("运行配置 · ANTHROPIC_API_KEY")
    ).toBeInTheDocument()
    expect(screen.getByText("secret_ref")).toBeInTheDocument()
    expect(screen.queryByText("未知依赖")).not.toBeInTheDocument()
  })

  it("renders canonical Oracle Host Port Service Name form and Secret selector", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/api/platform/resources")) {
        return response({ resources: [governedOracleResource()] })
      }
      if (url.includes("/api/platform/secrets")) {
        return response({ secrets: [platformSecret] })
      }
      if (url.includes("/api/platform/environments")) {
        return response({
          environments: [
            {
              id: "environment-local",
              code: "local",
              display_name: "本地环境",
              status: "enabled",
            },
          ],
        })
      }
      if (url.includes("/api/platform/bases")) {
        return response({
          bases: [
            {
              id: "base-one",
              code: "base-one",
              display_name: "一号基地",
              status: "enabled",
              environment_code: "local",
            },
          ],
        })
      }
      return response({ workshops: [] })
    })
    renderWithQuery(<ToolResourcesPage />)

    expect(await screen.findByText("Oracle 订单库")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "编辑草稿" }))
    expect(
      screen.getByRole("heading", { name: "编辑资源 Draft" })
    ).toBeInTheDocument()
    expect(
      screen.getByDisplayValue("oracle.example.internal")
    ).toBeInTheDocument()
    expect(screen.getByDisplayValue("1521")).toBeInTheDocument()
    expect(screen.getByDisplayValue("ORCL")).toBeInTheDocument()
    expect(screen.getByLabelText("密码凭据")).toBeInTheDocument()
    expect(screen.getByText(/仅保存 secret:\/\/platform/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/密码明文/)).not.toBeInTheDocument()
    expect(
      screen.queryByLabelText(/Connector|reply route|user_id/i)
    ).not.toBeInTheDocument()
  })

  it("keeps relational database names as text while ports stay numeric", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/api/platform/resources")) {
        return response({ resources: [] })
      }
      if (url.includes("/api/platform/secrets")) {
        return response({ secrets: [platformSecret] })
      }
      if (url.includes("/api/platform/environments")) {
        return response({ environments: [] })
      }
      if (url.includes("/api/platform/bases")) {
        return response({ bases: [] })
      }
      return response({ workshops: [] })
    })
    renderWithQuery(<ToolResourcesPage />)

    expect(
      await screen.findByText("当前筛选下没有工具资源")
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "新建资源" }))

    expect(screen.getByLabelText("Database")).toHaveAttribute("type", "text")
    expect(screen.getByLabelText("Port")).toHaveAttribute("type", "number")
  })

  it("shows the technical verification status and safe failure reason", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/verify")) {
        return response({
          verification: {
            id: "verification-oracle",
            status: "BLOCKED",
            checks: { available: false },
            safe_error_summary: "数据库客户端未安装，无法执行技术验证",
          },
        })
      }
      if (url.includes("/api/platform/resources")) {
        return response({ resources: [governedOracleResource()] })
      }
      return response({ secrets: [] })
    })
    renderWithQuery(<ToolResourcesPage />)

    expect(await screen.findByText("Oracle 订单库")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "技术测试" }))

    expect(
      await screen.findByText(
        "技术测试 BLOCKED：数据库客户端未安装，无法执行技术验证"
      )
    ).toBeInTheDocument()
  })

  it("serializes a resource Draft with only the selected Secret reference", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        resource: { id: "resource-oracle" },
        draft: governedOracleResource().draft,
      })
    )
    await createGovernedResource({
      code: "oracle_orders",
      name: "Oracle 订单库",
      resource_kind: "database",
      scope_type: "base",
      environment_code: "local",
      base_code: "base-one",
      workshop_code: "",
      provider_type: "oracle",
      config: {
        host: "oracle.example.internal",
        port: 1521,
        service_name: "ORCL",
        username: "reader",
      },
      secret_refs: {
        password_ref: "secret://platform/oracle_reader_password",
      },
    })

    const body = JSON.parse(
      String((fetchMock.mock.calls[0]?.[1] as RequestInit).body)
    )
    expect(body.secret_refs).toEqual({
      password_ref: "secret://platform/oracle_reader_password",
    })
    expect(body.config).not.toHaveProperty("password")
    expect(body).not.toHaveProperty("password")
    expect(JSON.stringify(body)).not.toContain("env:")
    expect(JSON.stringify(body)).not.toContain("vault:")
    expect(JSON.stringify(body)).not.toContain("kms:")
  })

  it("renders Debug options without arbitrary identity, resource, connector, or route inputs", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        environment: "local",
        default_delivery: { type: "none", binding_id: "" },
        applications: [
          {
            id: "application-one",
            code: "diagnosis-app",
            name: "诊断应用",
            project_code: "default",
            publication_id: "publication-one",
            publication_revision: 2,
            execution_scopes: [
              {
                id: "scope-one",
                scope_key: "local/base-one",
                environment_code: "local",
                base_code: "base-one",
                workshop_code: "",
              },
            ],
            delivery_bindings: [
              {
                binding_id: "delivery-one",
                binding_order: 1,
                delivery_type: "dingtalk_group",
                connector_id: "connector-governed",
              },
            ],
          },
        ],
      })
    )
    renderWithQuery(<DebugJobPage />)

    expect(await screen.findByText("创建 Agent Debug Job")).toBeInTheDocument()
    expect(screen.getByText(/默认不投递/)).toBeInTheDocument()
    expect(
      screen.queryByLabelText(/user_id|Agent ID|Resource Revision/i)
    ).not.toBeInTheDocument()
    expect(
      screen.queryByPlaceholderText(/Connector|目标地址|reply route/i)
    ).not.toBeInTheDocument()
  })

  it("submits Debug Job using only authorized option identifiers", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        accepted: true,
        status: "PENDING",
        job_id: "job-debug-one",
        idempotency_key: "debug:user:publication:scope:key",
      })
    )
    await createDebugJob({
      message: "检查数据库与日志异常关联",
      application_id: "application-one",
      execution_scope_id: "scope-one",
      delivery_binding_id: "",
      idempotency_key: "key",
    })

    const body = JSON.parse(
      String((fetchMock.mock.calls[0]?.[1] as RequestInit).body)
    )
    expect(body).toEqual({
      message: "检查数据库与日志异常关联",
      application_id: "application-one",
      execution_scope_id: "scope-one",
      delivery_binding_id: "",
      idempotency_key: "key",
    })
    expect(body).not.toHaveProperty("user_id")
    expect(body).not.toHaveProperty("agent_id")
    expect(body).not.toHaveProperty("resource_revision_id")
    expect(body).not.toHaveProperty("connector_id")
    expect(body).not.toHaveProperty("reply_route")
  })
})
