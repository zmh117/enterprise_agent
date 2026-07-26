import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { App } from "@/App"

function renderApp() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })
      }
    >
      <App />
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("Agent 应用平台 MVP 首页", () => {
  it("只展示已接线的业务应用和用户身份入口", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ count: 0 }), {
        headers: { "Content-Type": "application/json" },
      })
    )
    renderApp()

    expect(screen.getAllByText("Agent 应用平台").length).toBeGreaterThan(0)
    expect(screen.getAllByText("业务应用").length).toBeGreaterThan(0)
    expect(screen.getAllByText("用户与外部身份").length).toBeGreaterThan(0)
    expect(screen.getByText("统一身份边界")).toBeInTheDocument()
    expect(screen.getByText("钉钉身份")).toBeInTheDocument()
    expect(screen.getByText("ONES 身份")).toBeInTheDocument()
  })

  it("不保留旧模板业务文案", () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"))
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

  it("加载时只轮询候选计数且不建立流式连接", () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new Error("not expected"))
    const xhrOpenSpy = vi.spyOn(XMLHttpRequest.prototype, "open")
    const websocketSpy = vi.fn()
    const eventSourceSpy = vi.fn()
    vi.stubGlobal("WebSocket", websocketSpy)
    vi.stubGlobal("EventSource", eventSourceSpy)

    renderApp()

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/dingtalk-identity-candidates/count",
      expect.any(Object)
    )
    expect(xhrOpenSpy).not.toHaveBeenCalled()
    expect(websocketSpy).not.toHaveBeenCalled()
    expect(eventSourceSpy).not.toHaveBeenCalled()
  })

  it("不展示本次变更之外的规划入口", () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"))
    const { container } = renderApp()
    const page = container.textContent ?? ""

    for (const outOfScopeEntry of [
      "角色与授权",
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

  it("不暴露底层连接配置、凭据或可执行入口", () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"))
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
    expect(screen.getByText("统一身份边界")).toBeInTheDocument()
  })
})
