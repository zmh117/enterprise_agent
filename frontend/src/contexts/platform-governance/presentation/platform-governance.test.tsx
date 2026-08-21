import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import { createDebugJob } from "@/contexts/operations/infrastructure/debug-job-api"
import { DebugJobPage } from "@/contexts/operations/presentation/debug-job-page"
import { createGovernedResource } from "@/contexts/platform-governance/infrastructure/platform-governance-api"
import { CredentialCenterPage } from "@/contexts/platform-governance/presentation/credential-center-page"
import { RuntimeConfigPage } from "@/contexts/platform-governance/presentation/runtime-config-page"
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
    revision: 1,
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
      scope_bindings: [],
      status: "DRAFT",
      updated_at: "2026-07-29T00:00:00Z",
    },
    published_revision: null,
    safe_error_summary: "",
  }
}

function governedLokiResource({
  draft,
  published,
  code = "loki_test",
  name = "Loki 测试环境",
  identityStatus = "enabled",
  revisionStatus = "PUBLISHED",
}: {
  draft: boolean
  published: boolean
  code?: string
  name?: string
  identityStatus?: "enabled" | "disabled" | "archived"
  revisionStatus?: "PUBLISHED" | "DISABLED" | "ARCHIVED"
}) {
  return {
    id: `resource-${code}`,
    code,
    name,
    resource_kind: "loki",
    scope_type: "environment",
    environment_code: "agent_test",
    base_code: "",
    workshop_code: "",
    status: identityStatus,
    revision: 1,
    draft: draft
      ? {
          id: "resource-draft-loki-test",
          resource_id: "resource-loki-test",
          draft_revision: published ? 2 : 1,
          provider_type: "loki",
          config: {
            base_url: "http://localhost:3100",
            tenant_id: "tenant1",
            timeout_seconds: 5,
            max_minutes: 60,
            max_lines: 200,
            max_response_bytes: 65536,
          },
          secret_refs: {},
          scope_bindings: [
            {
              environment_code: "agent_test",
              selector_conditions: {},
            },
          ],
          status: "VERIFIED",
          updated_at: "2026-08-07T02:00:00Z",
        }
      : null,
    draft_verification: null,
    published_revision: published
      ? {
          id: "resource-revision-loki-test-1",
          resource_id: "resource-loki-test",
          revision: 1,
          provider_type: "loki",
          provider_contract_version: "loki_v1",
          config: {},
          secret_refs: {},
          scope_bindings: [
            {
              environment_code: "agent_test",
              selector_conditions: { cluster: "agent-test" },
            },
          ],
          status: revisionStatus,
          published_at: "2026-08-07T01:50:00Z",
        }
      : null,
    safe_error_summary: "",
  }
}

describe("Phase 5 platform governance UI", () => {
  it("exposes governance navigation with separate resources and credential center", () => {
    const group = navigationGroups.find((item) => item.label === "平台治理")
    expect(group?.items.map((item) => item.href)).toEqual([
      "/platform/resources",
      "/platform/secrets",
      "/platform/runtime-config",
    ])
    expect(group?.items.map((item) => item.requiredCapability)).toEqual([
      "platform.read",
      "secrets.read",
      "platform.read",
    ])
  })

  it("loads tenant quota diagnostics and saves both governed values with CAS", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.includes("file-workspace-diagnostics")) {
        return response({
          diagnostics: {
            tenant_id: "tenant-a",
            config_revision: 12,
            active_file_limit: { value: 200, source: "tenant", revision: 4 },
            billable_bytes_limit: {
              value: 2 * 1024 ** 3,
              source: "tenant",
              revision: 5,
            },
            usage: {
              workspace_count: 3,
              active_file_count: 120,
              billable_bytes: 1024,
              reserved_file_slots: 2,
              reserved_billable_bytes: 512,
            },
            incompatible_publications: [
              {
                application_code: "legacy-app",
                publication_id: "legacy-publication-1",
                publication_revision: 7,
              },
            ],
          },
        })
      }
      if (url.includes("/api/platform/runtime-config/values")) {
        if (init?.method === "POST") return response({ value: { status: "enabled" } })
        return response({
          values: [
            {
              id: "active-value",
              key: "FILE_WORKSPACE_ACTIVE_FILE_LIMIT",
              scope_type: "tenant",
              scope_code: "tenant-a",
              service_name: "file-service",
              revision: 4,
              value: 200,
              status: "enabled",
            },
            {
              id: "bytes-value",
              key: "FILE_WORKSPACE_BILLABLE_BYTES_LIMIT",
              scope_type: "tenant",
              scope_code: "tenant-a",
              service_name: "file-service",
              revision: 5,
              value: 2 * 1024 ** 3,
              status: "enabled",
            },
          ],
        })
      }
      return response({}, 404)
    })
    renderWithQuery(<RuntimeConfigPage />)

    fireEvent.change(screen.getByLabelText("Tenant ID"), {
      target: { value: "tenant-a" },
    })
    fireEvent.click(screen.getByRole("button", { name: "加载" }))

    expect(await screen.findByText("legacy-app · r7")).toBeInTheDocument()
    expect(screen.getByDisplayValue("200")).toBeInTheDocument()
    expect(screen.getByDisplayValue("2")).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("每工作区 ACTIVE 文件上限"), {
      target: { value: "250" },
    })
    fireEvent.change(screen.getByLabelText("每工作区计费容量（GiB）"), {
      target: { value: "3" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存 tenant 配额" }))

    expect(await screen.findByText("tenant 文件工作区配额已保存。")).toBeInTheDocument()
    const writes = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).includes("/api/platform/runtime-config/values") &&
        init?.method === "POST"
    )
    expect(writes).toHaveLength(2)
    expect(writes.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
      expect.objectContaining({
        key: "FILE_WORKSPACE_ACTIVE_FILE_LIMIT",
        value: 250,
        expected_revision: 4,
      }),
      expect.objectContaining({
        key: "FILE_WORKSPACE_BILLABLE_BYTES_LIMIT",
        value: 3 * 1024 ** 3,
        expected_revision: 5,
      }),
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

  it("accepts a custom environment code and explains the topology boundary", async () => {
    let createBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/api/platform/resources") && init?.method === "POST") {
        createBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return response({
          resource: { id: "resource-customer-prod" },
          draft: {
            id: "draft-customer-prod",
            resource_id: "resource-customer-prod",
            draft_revision: 1,
            provider_type: "redis",
            config: {
              host: "redis.internal",
              port: 6379,
              database: 0,
              username: "",
              tls: { enabled: false, verify_certificate: true },
            },
            secret_refs: {},
            status: "DRAFT",
            updated_at: "2026-08-11T00:00:00Z",
          },
        })
      }
      if (url.includes("/api/platform/resources")) {
        return response({ resources: [] })
      }
      if (url.includes("/api/platform/secrets")) {
        return response({ secrets: [] })
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

    const environment = screen.getByLabelText("环境")
    fireEvent.focus(environment)
    fireEvent.click(environment)
    fireEvent.input(environment, {
      target: { value: "customer_prod" },
      inputType: "insertText",
    })

    expect(environment).toHaveValue("customer_prod")
    expect(
      screen.getByText(
        "新环境只能用于环境级作用域；基地或车间作用域必须选择已有环境。"
      )
    ).toBeInTheDocument()

    const resourceName = screen.getByLabelText("资源名称")
    fireEvent.blur(environment, { relatedTarget: resourceName })
    fireEvent.focus(resourceName)
    expect(environment).toHaveValue("customer_prod")

    const scope = await screen.findByRole("combobox", { name: "作用域层级" })
    fireEvent.click(scope)
    const environmentScope = await screen.findByRole("option", { name: "环境" })
    fireEvent.pointerDown(environmentScope, {
      pointerType: "mouse",
      button: 0,
    })
    fireEvent.click(environmentScope)
    expect(environment).toHaveValue("customer_prod")
    expect(
      await screen.findByText(
        "环境“customer_prod”尚不存在，保存 Draft 时将同时创建。"
      )
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole("combobox", { name: "Provider" }))
    const redisProvider = await screen.findByRole("option", { name: "Redis" })
    fireEvent.pointerDown(redisProvider, { pointerType: "mouse", button: 0 })
    fireEvent.click(redisProvider)
    fireEvent.change(screen.getByLabelText("资源编码"), {
      target: { value: "customer_prod_redis" },
    })
    fireEvent.change(screen.getByLabelText("资源名称"), {
      target: { value: "Customer Prod Redis" },
    })
    fireEvent.change(screen.getByLabelText("Host"), {
      target: { value: "redis.internal" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存 Draft" }))

    await waitFor(() =>
      expect(createBody).toMatchObject({
        scope_type: "environment",
        environment_code: "customer_prod",
        base_code: "",
        workshop_code: "",
        create_environment_if_missing: true,
      })
    )
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

  it("discovers arbitrary Loki labels and saves the exact selector in the same Draft", async () => {
    let savedBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/api/platform/resources/loki_test/loki/test")) {
        return response({
          test_session_id: "loki-session-1",
          draft_revision: 1,
          labels: ["cluster", "kubernetes_namespace_name"],
          label_count: 2,
          truncated: false,
          expires_at: "2026-08-17T12:05:00Z",
        })
      }
      if (url.endsWith("/api/platform/resources/loki_test/loki/label-values")) {
        return response({
          label: "kubernetes_namespace_name",
          values: ["mes-production"],
          value_count: 1,
          truncated: false,
        })
      }
      if (url.endsWith("/api/platform/resources/loki_test/draft") && init?.method === "PUT") {
        savedBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return response({
          draft: {
            ...governedLokiResource({ draft: true, published: false }).draft,
            draft_revision: 2,
            scope_bindings: (savedBody.scope_bindings as unknown[]) ?? [],
          },
        })
      }
      if (url.endsWith("/api/platform/resources")) {
        return response({ resources: [governedLokiResource({ draft: true, published: false })] })
      }
      if (url.includes("/api/platform/secrets")) return response({ secrets: [] })
      if (url.includes("/api/platform/environments")) {
        return response({
          environments: [
            {
              id: "environment-agent-test",
              code: "agent_test",
              display_name: "Agent Test",
              status: "enabled",
            },
          ],
        })
      }
      if (url.includes("/api/platform/bases")) return response({ bases: [] })
      if (url.includes("/api/platform/workshops")) return response({ workshops: [] })
      if (url.includes("/api/platform/provider-contracts")) return response({ contracts: [] })
      throw new Error(`unexpected request: ${url}`)
    })
    renderWithQuery(<ToolResourcesPage />)

    expect(await screen.findByText("Loki 测试环境")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "编辑草稿" }))
    fireEvent.click(screen.getByRole("button", { name: "连接并发现 Labels" }))

    const labelSelect = await screen.findByRole("combobox", {
      name: "范围 1 Loki label",
    })
    fireEvent.click(labelSelect)
    const labelOption = await screen.findByRole("option", {
      name: "kubernetes_namespace_name",
    })
    fireEvent.pointerDown(labelOption, { pointerType: "mouse", button: 0 })
    fireEvent.click(labelOption)
    fireEvent.click(screen.getByRole("button", { name: "查值" }))

    const valueSelect = await screen.findByRole("combobox", {
      name: "范围 1 Loki value",
    })
    await waitFor(() => expect(valueSelect).not.toBeDisabled())
    fireEvent.click(valueSelect)
    const valueOption = await screen.findByRole("option", {
      name: "mes-production",
    })
    fireEvent.pointerDown(valueOption, { pointerType: "mouse", button: 0 })
    fireEvent.click(valueOption)
    fireEvent.click(screen.getByRole("button", { name: "添加" }))

    expect(screen.getByLabelText("范围 1 最终 Selector")).toHaveValue(
      '{kubernetes_namespace_name="mes-production"}'
    )
    fireEvent.click(screen.getByRole("button", { name: "保存 Draft" }))

    await waitFor(() =>
      expect(savedBody).toMatchObject({
        scope_bindings: [
          {
            environment_code: "agent_test",
            selector_conditions: {
              kubernetes_namespace_name: "mes-production",
            },
          },
        ],
      })
    )
  })

  it("creates a new Resource Draft directly from a Published revision", async () => {
    let copied = false
    let copyBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/resources/loki_test/draft/from-revision")) {
        copied = true
        copyBody = JSON.parse(String(init?.body)) as Record<string, unknown>
        return response({
          draft: governedLokiResource({ draft: true, published: true }).draft,
        })
      }
      if (url === "/api/platform/resources") {
        return response({
          resources: [governedLokiResource({ draft: copied, published: true })],
        })
      }
      if (url === "/api/platform/secrets") return response({ secrets: [] })
      if (url.startsWith("/api/platform/environments")) {
        return response({
          environments: [
            {
              id: "environment-agent-test",
              code: "agent_test",
              display_name: "Agent 测试环境",
              status: "enabled",
            },
          ],
        })
      }
      if (url.startsWith("/api/platform/bases")) return response({ bases: [] })
      if (url.startsWith("/api/platform/workshops")) {
        return response({ workshops: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderWithQuery(<ToolResourcesPage />)

    fireEvent.click(
      await screen.findByRole("button", {
        name: "从 r1 新建草稿",
      })
    )

    await waitFor(() =>
      expect(copyBody).toEqual({
        revision_id: "resource-revision-loki-test-1",
      })
    )
    expect(
      await screen.findByRole("button", { name: "编辑草稿" })
    ).toBeInTheDocument()
  })

  it("publishes a verified Resource Draft directly", async () => {
    let published = false
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/resources/loki_test/publish")) {
        published = true
        return response({
          revision: governedLokiResource({ draft: false, published: true })
            .published_revision,
        })
      }
      if (url === "/api/platform/resources") {
        return response({
          resources: [governedLokiResource({ draft: !published, published })],
        })
      }
      if (url === "/api/platform/secrets") return response({ secrets: [] })
      if (url.startsWith("/api/platform/environments")) {
        return response({
          environments: [
            {
              id: "environment-agent-test",
              code: "agent_test",
              display_name: "Agent 测试环境",
              status: "enabled",
            },
          ],
        })
      }
      if (url.startsWith("/api/platform/bases")) return response({ bases: [] })
      if (url.startsWith("/api/platform/workshops")) {
        return response({ workshops: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderWithQuery(<ToolResourcesPage />)

    fireEvent.click(await screen.findByRole("button", { name: "发布" }))

    await waitFor(() => expect(published).toBe(true))
    expect(await screen.findByText("r1 · PUBLISHED")).toBeInTheDocument()
  })

  it("shows revision transition failures inside the confirmation dialog", async () => {
    let disableRequest = ""
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/disable")) {
        disableRequest = url
        return response(
          {
            detail: {
              code: "resource_revision_immutable",
              message: "已发布资源只能禁用或归档，不能原地修改",
            },
          },
          400
        )
      }
      if (url === "/api/platform/resources") {
        return response({
          resources: [governedLokiResource({ draft: false, published: true })],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderWithQuery(<ToolResourcesPage />)

    fireEvent.click(await screen.findByRole("button", { name: "停用发布版本" }))
    fireEvent.click(screen.getByRole("button", { name: "确认" }))

    await waitFor(() =>
      expect(disableRequest).toBe(
        "/api/platform/resources/loki_test/revisions/resource-revision-loki-test-1/disable"
      )
    )
    const dialog = screen.getByRole("alertdialog")
    expect(
      await within(dialog).findByText("已发布资源只能禁用或归档，不能原地修改")
    ).toBeInTheDocument()
    expect(
      within(dialog).getByRole("heading", { name: "停用已发布版本？" })
    ).toBeInTheDocument()
  })

  it("separates Resource Identity and latest Revision lifecycle filters", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url === "/api/platform/resources") {
        return response({
          resources: [
            governedLokiResource({
              draft: false,
              published: true,
              code: "loki_archived_revision",
              name: "归档版本 Loki",
              identityStatus: "enabled",
              revisionStatus: "ARCHIVED",
            }),
            governedLokiResource({
              draft: false,
              published: true,
              code: "loki_current_revision",
              name: "当前版本 Loki",
            }),
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderWithQuery(<ToolResourcesPage />)

    expect(await screen.findByText("归档版本 Loki")).toBeInTheDocument()
    expect(screen.getByText("当前版本 Loki")).toBeInTheDocument()
    expect(screen.getAllByText("资源身份：启用").length).toBe(2)

    fireEvent.click(screen.getByRole("combobox", { name: "最新发布版本状态" }))
    const archivedOption = await screen.findByRole("option", {
      name: "已归档",
    })
    fireEvent.pointerDown(archivedOption, { pointerType: "mouse", button: 0 })
    fireEvent.click(archivedOption)
    expect(screen.getByText("归档版本 Loki")).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByText("当前版本 Loki")).not.toBeInTheDocument()
    )
    expect(
      screen.getByRole("button", { name: "从 r1 新建草稿" })
    ).toBeInTheDocument()
  })

  it("changes Resource Identity lifecycle with its expected revision", async () => {
    let lifecycleRequest = ""
    let lifecycleBody: Record<string, unknown> | undefined
    const resource = governedLokiResource({
      draft: false,
      published: true,
      revisionStatus: "ARCHIVED",
    })
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/resources/loki_test/lifecycle/disable")) {
        lifecycleRequest = url
        lifecycleBody = JSON.parse(String(init?.body)) as Record<
          string,
          unknown
        >
        return response({
          resource: {
            id: resource.id,
            code: resource.code,
            status: "disabled",
            revision: 2,
          },
        })
      }
      if (url === "/api/platform/resources") {
        return response({ resources: [resource] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderWithQuery(<ToolResourcesPage />)

    fireEvent.click(await screen.findByRole("button", { name: "停用资源身份" }))
    fireEvent.click(screen.getByRole("button", { name: "确认" }))

    await waitFor(() =>
      expect(lifecycleRequest).toBe(
        "/api/platform/resources/loki_test/lifecycle/disable"
      )
    )
    expect(lifecycleBody).toEqual({ expected_revision: 1 })
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
      scope_bindings: [],
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
