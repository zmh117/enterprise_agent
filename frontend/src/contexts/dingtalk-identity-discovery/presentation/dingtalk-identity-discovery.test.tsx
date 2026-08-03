import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PlatformNavigation } from "@/app/navigation/platform-navigation"
import { SidebarProvider } from "@/components/ui/sidebar"
import { AuthenticatedUserProvider } from "@/contexts/auth/presentation/authenticated-user-context"
import { DingTalkIdentityDiscoveryPage } from "@/contexts/dingtalk-identity-discovery/presentation/dingtalk-identity-discovery-page"

const currentUser = {
  id: "user-local-admin",
  username: "local-admin",
  display_name: "本地管理员",
  roles: ["platform-admin"],
  auth_source: "local",
  capabilities: {},
}

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

function candidate(overrides: Record<string, unknown> = {}) {
  const message = {
    id: "message-1",
    connector_id: "connector-1",
    connector_name: "华东钉钉机器人",
    robot_code: "robot-east",
    conversation_type: "group",
    conversation_id: "cid-group-1",
    message_kind: "text",
    safe_text: "<img src=x onerror=alert(1)>",
    text_truncated: false,
    attachment_type: "",
    attachment_name: "",
    attachment_size: null,
    occurred_at: "2026-07-26T01:00:00+00:00",
    received_at: "2026-07-26T01:00:01+00:00",
  }
  return {
    id: "candidate-1",
    dingtalk_enterprise_id: "enterprise-east",
    enterprise_name: "华东示例企业",
    corp_id: "corp-east",
    external_subject_id: "staff-001",
    display_name: "张三",
    first_seen_at: "2026-07-26T01:00:01+00:00",
    last_seen_at: "2026-07-26T01:00:01+00:00",
    observation_count: 3,
    revision: 4,
    identity_state: "waiting_bind",
    conversation_scope: "group",
    group_ids: ["cid-group-1"],
    robot_codes: ["robot-east"],
    connector_names: ["华东钉钉机器人"],
    latest_message: message,
    messages: [message],
    historical_identity: null,
    ...overrides,
  }
}

function renderWithQuery(ui: React.ReactNode, initialEntry: string) {
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
      <MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  })
})

describe("未绑定钉钉用户发现", () => {
  it("展示安全纯文本、群 ID、机器人并使用候选 ID 去绑定", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        candidates: [candidate()],
        next_cursor: "",
        has_more: false,
      })
    )
    const view = renderWithQuery(
      <DingTalkIdentityDiscoveryPage />,
      "/users/dingtalk-discovery"
    )

    expect(await screen.findByText("张三")).toBeInTheDocument()
    expect(screen.getAllByText("<img src=x onerror=alert(1)>")).toHaveLength(2)
    expect(view.container.querySelector("img")).toBeNull()
    expect(screen.getByText("staff-001")).toBeInTheDocument()
    expect(screen.getByText("cid-group-1")).toBeInTheDocument()
    expect(screen.getByText("robot-east")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "去绑定" })).toHaveAttribute(
      "href",
      "/users?candidate=candidate-1"
    )
    for (const forbidden of ["回复", "发送消息", "忽略", "删除", "下载"]) {
      expect(screen.queryByRole("button", { name: forbidden })).toBeNull()
    }
  })

  it("把搜索与会话构成筛选提交给服务端", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() =>
        response({ candidates: [], next_cursor: "", has_more: false })
      )
    renderWithQuery(
      <DingTalkIdentityDiscoveryPage />,
      "/users/dingtalk-discovery"
    )
    await screen.findByText("当前没有待绑定的钉钉用户。")

    fireEvent.change(screen.getByLabelText("会话类型"), {
      target: { value: "both" },
    })
    fireEvent.change(screen.getByLabelText("搜索未绑定钉钉用户"), {
      target: { value: "robot-east" },
    })
    fireEvent.click(screen.getByRole("button", { name: "搜索" }))

    await waitFor(() => {
      const lastUrl = new URL(
        String(fetch.mock.calls.at(-1)?.[0]),
        "http://admin.test"
      )
      expect(lastUrl.searchParams.get("conversation_scope")).toBe("both")
      expect(lastUrl.searchParams.get("search")).toBe("robot-east")
    })
  })

  it("历史身份只允许前往原人员恢复", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        candidates: [
          candidate({
            identity_state: "restore_required",
            historical_identity: {
              id: "identity-old",
              status: "unbound",
              revision: 3,
              user_id: "user-original",
              username: "original",
              user_display_name: "原人员",
              user_status: "enabled",
            },
          }),
        ],
        next_cursor: "",
        has_more: false,
      })
    )
    renderWithQuery(
      <DingTalkIdentityDiscoveryPage />,
      "/users/dingtalk-discovery"
    )

    expect(
      await screen.findByRole("link", { name: "前往原人员恢复" })
    ).toHaveAttribute("href", "/users/user-original?candidate=candidate-1")
    expect(screen.queryByRole("link", { name: "去绑定" })).toBeNull()
  })

  it("徽标显示 99+，页面隐藏时暂停并在恢复前台时立即刷新", async () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    })
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      String(input).endsWith("/api/admin/capabilities")
        ? response({
            capabilities: ["identity.discovery.read"],
            modules: {},
          })
        : response({ count: 120 })
    )
    renderWithQuery(
      <AuthenticatedUserProvider user={currentUser}>
        <SidebarProvider>
          <PlatformNavigation />
        </SidebarProvider>
      </AuthenticatedUserProvider>,
      "/users/dingtalk-discovery"
    )

    expect(await screen.findByText("99+")).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(2)
    vi.useFakeTimers()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(fetch).toHaveBeenCalledTimes(2)

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    })
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"))
      await Promise.resolve()
    })
    expect(fetch.mock.calls.length).toBeGreaterThan(1)
  })
})
