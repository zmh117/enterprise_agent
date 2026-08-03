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
import { ManagedChannelsPanel } from "@/contexts/applications/presentation/managed-channels-panel"

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

function renderWithQuery(
  ui: React.ReactNode,
  initialEntries: string[] = ["/"]
) {
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
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

const dingTalkEnterprise = {
  id: "enterprise-default",
  name: "默认钉钉企业",
  corp_id: "corp-default",
  status: "ACTIVE",
  verified_at: "2026-07-25T17:00:00+08:00",
  revision: 3,
  connector_count: 1,
  enabled_connector_count: 1,
  created_at: "2026-07-25T16:00:00+08:00",
  updated_at: "2026-07-25T17:00:00+08:00",
}

const dingTalkChannel = {
  id: "connector-dingtalk-a",
  kind: "DINGTALK_APP_ROBOT",
  name: "生产诊断机器人",
  client_id: "ding-client-a",
  enterprise: {
    id: dingTalkEnterprise.id,
    name: dingTalkEnterprise.name,
    status: dingTalkEnterprise.status,
    corp_id_verified: true,
    verified_at: dingTalkEnterprise.verified_at,
  },
  enabled: true,
  revision: 4,
  secret_configured: true,
  capabilities: {
    private_chat: true,
    group_chat: true,
    require_group_at: true,
  },
  runtime: {
    status: "READY",
    loaded_revision: 4,
    last_heartbeat_at: "2026-07-25T18:00:00+08:00",
    last_message_at: null,
    last_error: "",
  },
}

describe("Managed channels", () => {
  it("creates a pending enterprise and selects it instead of accepting a free tenant value", async () => {
    const enterprises: Array<Record<string, unknown>> = []
    let channelBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/webhook-connector-options")) {
        return response({ items: [] })
      }
      if (url.endsWith("/dingtalk-enterprises") && init?.method === "POST") {
        const created = {
          ...dingTalkEnterprise,
          id: "enterprise-new",
          name: "新建测试企业",
          corp_id: "",
          status: "PENDING_VERIFICATION",
          verified_at: null,
          revision: 1,
          connector_count: 0,
          enabled_connector_count: 0,
        }
        enterprises.push(created)
        return response({ enterprise: created })
      }
      if (url.endsWith("/dingtalk-enterprises")) {
        return response({ items: enterprises })
      }
      if (url.endsWith("/dingtalk-app-robots") && init?.method === "POST") {
        channelBody = JSON.parse(String(init.body))
        return response({
          channel: {
            ...dingTalkChannel,
            id: "connector-new",
            name: "新机器人",
            client_id: "new-client",
            enabled: false,
            revision: 1,
            enterprise: {
              id: "enterprise-new",
              name: "新建测试企业",
              status: "PENDING_VERIFICATION",
              corp_id_verified: false,
              verified_at: null,
            },
            runtime: { ...dingTalkChannel.runtime, status: "STOPPED" },
          },
        })
      }
      if (url.endsWith("/api/admin/managed-channels")) {
        return response({ items: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderWithQuery(<ManagedChannelsPanel />)
    fireEvent.click(await screen.findByRole("button", { name: "新建钉钉企业" }))
    fireEvent.change(screen.getByLabelText("企业名称"), {
      target: { value: "新建测试企业" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建待验证企业" }))
    expect(await screen.findByText("新建测试企业")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "新建钉钉机器人" }))
    expect(screen.queryByLabelText("企业标识（Corp / Tenant）")).toBeNull()
    fireEvent.change(await screen.findByLabelText("渠道名称"), {
      target: { value: "新机器人" },
    })
    fireEvent.change(screen.getByLabelText("Client ID / AppKey"), {
      target: { value: "new-client" },
    })
    fireEvent.change(screen.getByLabelText("钉钉企业"), {
      target: { value: "enterprise-new" },
    })
    fireEvent.change(screen.getByLabelText("Client Secret / AppSecret"), {
      target: { value: "test-only-secret" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建渠道" }))
    await waitFor(() => expect(channelBody).toBeDefined())
    expect(channelBody).toMatchObject({
      dingtalk_enterprise_id: "enterprise-new",
      name: "新机器人",
      client_id: "new-client",
    })
    expect(channelBody).not.toHaveProperty("tenant_code")
  })

  it("separates pending enterprise verification from a connected runtime and previews governance impacts", async () => {
    const pendingEnterprise = {
      ...dingTalkEnterprise,
      status: "PENDING_VERIFICATION",
      corp_id: "",
      verified_at: null,
    }
    const pendingChannel = {
      ...dingTalkChannel,
      enterprise: {
        id: pendingEnterprise.id,
        name: pendingEnterprise.name,
        status: "PENDING_VERIFICATION",
        corp_id_verified: false,
        verified_at: null,
      },
      runtime: { ...dingTalkChannel.runtime, status: "CONNECTED" },
    }
    let disableBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/webhook-connector-options"))
        return response({ items: [] })
      if (
        url.endsWith(`/dingtalk-enterprises/${pendingEnterprise.id}/disable`)
      ) {
        disableBody = JSON.parse(String(init?.body ?? "{}"))
        return response({
          enterprise: { ...pendingEnterprise, status: "DISABLED", revision: 4 },
        })
      }
      if (url.endsWith(`/dingtalk-enterprises/${pendingEnterprise.id}`)) {
        return response({
          enterprise: {
            ...pendingEnterprise,
            impacts: [
              {
                connector_id: pendingChannel.id,
                connector_name: pendingChannel.name,
                connector_enabled: true,
                application_id: "app-1",
                application_name: "诊断应用",
                application_revision: 2,
              },
            ],
          },
        })
      }
      if (url.endsWith("/dingtalk-enterprises")) {
        return response({ items: [pendingEnterprise] })
      }
      if (url.endsWith("/api/admin/managed-channels")) {
        return response({ items: [pendingChannel] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderWithQuery(<ManagedChannelsPanel />)
    expect(await screen.findAllByText("待企业验证")).not.toHaveLength(0)
    expect(screen.getAllByText("已连接")).not.toHaveLength(0)
    expect(screen.getByText(/已连接，等待企业验证/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "停用企业" }))
    expect(await screen.findByText(/诊断应用/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "停用钉钉企业" }))
    await waitFor(() => expect(disableBody).toEqual({ expected_revision: 3 }))
  })

  it("lists business application references before allowing channel deletion", async () => {
    const referencedChannel = {
      ...dingTalkChannel,
      enabled: false,
      references: [
        {
          application_code: "diagnostic-app",
          application_name: "诊断应用",
          application_revision: 7,
          trigger_type: "dingtalk_private",
        },
      ],
      runtime: { ...dingTalkChannel.runtime, status: "STOPPED" },
    }
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/webhook-connector-options")) {
        return response({ items: [] })
      }
      if (url.endsWith("/dingtalk-enterprises")) {
        return response({ items: [dingTalkEnterprise] })
      }
      if (url.endsWith("/api/admin/managed-channels")) {
        return response({ items: [referencedChannel] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderWithQuery(<ManagedChannelsPanel />)
    await screen.findByText("生产诊断机器人")
    fireEvent.click(screen.getByRole("button", { name: "删除" }))

    expect(
      await screen.findByRole("heading", { name: "删除钉钉应用连接？" })
    ).toBeInTheDocument()
    expect(screen.getByText(/诊断应用 · r7 · dingtalk_private/)).toBeVisible()
    expect(screen.getByRole("button", { name: "确认删除" })).toBeDisabled()
  })

  it("shows runtime state and keeps the existing secret when edit is blank", async () => {
    const requests: Array<{ url: string; body: unknown }> = []
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (
        url.endsWith("/api/admin/managed-channels/webhook-connector-options")
      ) {
        return response({ items: [] })
      }
      if (url.endsWith("/api/admin/managed-channels/dingtalk-enterprises")) {
        return response({ items: [dingTalkEnterprise] })
      }
      if (
        url.endsWith(
          "/api/admin/managed-channels/dingtalk-app-robots/connector-dingtalk-a"
        )
      ) {
        requests.push({
          url,
          body: JSON.parse(String(init?.body ?? "{}")),
        })
        return response({
          channel: { ...dingTalkChannel, name: "更新后的机器人", revision: 5 },
        })
      }
      return response({ items: [dingTalkChannel] })
    })

    renderWithQuery(<ManagedChannelsPanel />)
    expect(await screen.findByText("生产诊断机器人")).toBeInTheDocument()
    expect(screen.getAllByText("已就绪")).toHaveLength(2)

    fireEvent.click(screen.getByRole("button", { name: "编辑" }))
    const secret = await screen.findByLabelText("Client Secret / AppSecret")
    expect(secret).toHaveValue("")
    fireEvent.change(screen.getByLabelText("渠道名称"), {
      target: { value: "更新后的机器人" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }))

    await waitFor(() => expect(requests).toHaveLength(1))
    expect(requests[0].body).toMatchObject({
      expected_revision: 4,
      client_secret: "",
      rotate_secret: false,
      name: "更新后的机器人",
      dingtalk_enterprise_id: "enterprise-default",
    })
  })

  it("shows MISCONFIGURED safely and tests only the saved credential reference", async () => {
    const misconfigured = {
      ...dingTalkChannel,
      runtime: {
        ...dingTalkChannel.runtime,
        status: "MISCONFIGURED",
        last_error: "连接器凭据缺失、已停用或无法解析，请重新绑定后测试",
      },
    }
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (
        url.endsWith("/api/admin/managed-channels/webhook-connector-options")
      ) {
        return response({ items: [] })
      }
      if (url.endsWith("/api/admin/managed-channels/dingtalk-enterprises")) {
        return response({ items: [dingTalkEnterprise] })
      }
      if (
        url.endsWith("/api/admin/managed-channels/connector-dingtalk-a/test")
      ) {
        return response({
          result: {
            status: "READY",
            summary: "已保存的连接器凭据引用可以安全解析；未执行外部网络请求",
            tested_at: "2026-07-28T18:00:00+08:00",
          },
        })
      }
      return response({ items: [misconfigured] })
    })

    renderWithQuery(<ManagedChannelsPanel />)
    expect(await screen.findAllByText("配置异常")).toHaveLength(2)
    expect(
      screen.getByText("连接器凭据缺失、已停用或无法解析，请重新绑定后测试")
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "测试配置" }))
    expect(
      await screen.findByText(
        "已保存的连接器凭据引用可以安全解析；未执行外部网络请求"
      )
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "编辑" }))
    expect(
      await screen.findByText(/当前凭据不可用，请填写新 Secret 保存/)
    ).toBeInTheDocument()
  })

  it("filters trigger choices through the eligible channel endpoint", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/eligible?trigger_type=dingtalk_group")) {
        return response({ items: [dingTalkChannel] })
      }
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
          description: "",
          project_code: "default",
          owner_user_id: "",
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
            triggers: [
              {
                trigger_type: "dingtalk_group",
                connector_id: "connector-dingtalk-a",
                routing_key: "conversation:cid-a",
                actor_policy: "CURRENT_SENDER",
                service_account_user_id: "",
                enabled: true,
                config: {
                  conversation_type: "group",
                  require_mention: true,
                  webhook_definition_id: "",
                },
              },
            ],
            deliveries: [],
            capabilities: [],
          },
          publications: [],
          deployments: [],
        },
      })
    })

    renderWithQuery(
      <Routes>
        <Route path="/applications/:code" element={<ApplicationDetailPage />} />
      </Routes>,
      ["/applications/real-app"]
    )
    fireEvent.click(await screen.findByRole("tab", { name: "组成配置" }))
    const selector = await screen.findByLabelText("入口渠道")
    expect(
      await screen.findByRole("option", { name: /生产诊断机器人/ })
    ).toBeInTheDocument()
    expect(selector).toHaveValue("connector-dingtalk-a")
    expect(
      within(selector).queryByRole("option", { name: /Webhook/ })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("tab", { name: "渠道与触发器" })
    ).not.toBeInTheDocument()
  })
})
