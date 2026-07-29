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

const dingTalkChannel = {
  id: "connector-dingtalk-a",
  kind: "DINGTALK_APP_ROBOT",
  name: "生产诊断机器人",
  client_id: "ding-client-a",
  tenant_code: "default",
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
  it("shows runtime state and keeps the existing secret when edit is blank", async () => {
    const requests: Array<{ url: string; body: unknown }> = []
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (
        url.endsWith("/api/admin/managed-channels/webhook-connector-options")
      ) {
        return response({ items: [] })
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
    expect(screen.getByText("已就绪")).toBeInTheDocument()

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
      if (
        url.endsWith(
          "/api/admin/managed-channels/connector-dingtalk-a/test"
        )
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
    expect(await screen.findByText("配置异常")).toBeInTheDocument()
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
