import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "@/App"
import { AuthenticatedUserProvider } from "@/contexts/auth/presentation/authenticated-user-context"

const platformCapabilities = {
  capabilities: [
    "dashboard.read",
    "applications.read",
    "channels.read",
    "agents.read",
    "users.read",
    "authorization.read",
    "identity.discovery.read",
    "jobs.read",
  ],
  modules: {},
}

const currentUser = {
  id: "user-local-admin",
  username: "local-admin",
  display_name: "本地管理员",
  roles: ["platform-admin"],
  auth_source: "local",
  capabilities: {},
}

function platformResponse(input: RequestInfo | URL) {
  const url = String(input)
  const body = url.endsWith("/api/admin/capabilities")
    ? platformCapabilities
    : { count: 0 }
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      headers: { "Content-Type": "application/json" },
    })
  )
}

function renderApp() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })
      }
    >
      <AuthenticatedUserProvider user={currentUser}>
        <App />
      </AuthenticatedUserProvider>
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("Agent 应用平台 MVP 首页", () => {
  it("只展示已接线的业务应用和用户身份入口", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(platformResponse)
    renderApp()

    expect(screen.getAllByText("Agent 应用平台").length).toBeGreaterThan(0)
    expect((await screen.findAllByText("业务应用")).length).toBeGreaterThan(0)
    expect(screen.getAllByText("用户与外部身份").length).toBeGreaterThan(0)
    expect(screen.getByText("统一身份边界")).toBeInTheDocument()
    expect(screen.getByText("钉钉身份")).toBeInTheDocument()
    expect(screen.getByText("ONES 身份")).toBeInTheDocument()
  })

  it("不保留旧模板业务文案", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(platformResponse)
    const { container } = renderApp()
    const page = container.textContent ?? ""

    for (const legacyText of [
      "Acme",
      "Revenue",
      "Visitors",
      "Documents",
      "Projects",
      "Lifecycle",
    ]) {
      expect(page).not.toContain(legacyText)
    }
  })

  it("加载时只轮询候选计数且不建立流式连接", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(platformResponse)
    const xhrOpenSpy = vi.spyOn(XMLHttpRequest.prototype, "open")
    const websocketSpy = vi.fn()
    const eventSourceSpy = vi.fn()
    vi.stubGlobal("WebSocket", websocketSpy)
    vi.stubGlobal("EventSource", eventSourceSpy)

    renderApp()

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/capabilities",
      expect.any(Object)
    )
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/dingtalk-identity-candidates/count",
        expect.any(Object)
      )
    )
    expect(xhrOpenSpy).not.toHaveBeenCalled()
    expect(websocketSpy).not.toHaveBeenCalled()
    expect(eventSourceSpy).not.toHaveBeenCalled()
  })

  it("不展示本次变更之外的规划入口", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(platformResponse)
    const { container } = renderApp()
    const page = container.textContent ?? ""

    for (const outOfScopeEntry of [
      "审计日志",
      "环境管理",
      "API Capability",
      "平台连接",
      "Agent 任务",
      "会话记录",
      "冲突中心",
      "需求主体",
      "任务与缺陷主体",
    ]) {
      expect(page).not.toContain(outOfScopeEntry)
    }
  })

  it("不暴露底层连接配置、凭据或可执行入口", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(platformResponse)
    const { container } = renderApp()
    const page = container.textContent ?? ""

    for (const forbiddenEntry of [
      "数据库连接",
      "缓存地址",
      "日志平台地址",
      "连接字符串",
      "凭据 URI",
      "AppSecret",
      "Webhook Secret",
      "执行 Shell",
      "执行任意请求",
    ]) {
      expect(page).not.toContain(forbiddenEntry)
    }
    expect(await screen.findByText("统一身份边界")).toBeInTheDocument()
  })
})
