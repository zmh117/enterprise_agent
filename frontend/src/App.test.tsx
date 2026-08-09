import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"
import { RouterProvider, createMemoryRouter } from "react-router-dom"

import { appRoutes } from "@/app/router/app-router"
import { AuthenticatedUserProvider } from "@/contexts/auth/presentation/authenticated-user-context"

const currentUser = {
  id: "user-local-admin",
  username: "local-admin",
  display_name: "本地用户",
  roles: ["platform-admin"],
  auth_source: "local",
  capabilities: {},
}

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }))
}

function renderApp(path = "/") {
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] })
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthenticatedUserProvider user={currentUser}><RouterProvider router={router} /></AuthenticatedUserProvider>
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  window.history.pushState({}, "", "/")
})

describe("轻量用户门户", () => {
  it("首页只保留本人历史、身份和账户安全入口", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => response({ items: [], page: { limit: 50, has_more: false, next_cursor: null } }))
    window.history.pushState({}, "", "/")
    renderApp("/")
    expect(await screen.findByRole("heading", { name: "Agent Job" })).toBeInTheDocument()
    expect(screen.getAllByText("Job 与会话历史").length).toBeGreaterThan(0)
    expect(screen.getAllByText("我的外部身份").length).toBeGreaterThan(0)
    expect(screen.getAllByText("密码与会话").length).toBeGreaterThan(0)
    for (const removed of ["业务应用", "API Capability", "平台资源", "角色授权", "Agent 配置"]) {
      expect(document.body.textContent).not.toContain(removed)
    }
  })

  it("历史首页只查询当前用户接口，不查询管理员控制面", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => response({ items: [], page: { limit: 50, has_more: false, next_cursor: null } }))
    window.history.pushState({}, "", "/operations/jobs")
    renderApp("/operations/jobs")
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const urls = fetch.mock.calls.map(([input]) => String(input))
    expect(urls).toContain("/api/me/jobs?limit=50")
    expect(urls.some((url) => url.startsWith("/api/admin/"))).toBe(false)
  })

  it("旧管理 URL 明确返回已退役页面", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => response({}))
    renderApp("/platform/api-capabilities")
    expect(await screen.findByRole("heading", { name: "管理工作台已退役" })).toBeInTheDocument()
    expect(screen.getByText(/platformctl/)).toBeInTheDocument()
  })

  it("窄屏下本人身份操作保持可聚焦且表单具有键盘可访问标签", async () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 375,
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({
        user: { id: "user-local-admin", display_name: "本地用户" },
        dingtalk: [],
        ones: null,
      })
    )

    renderApp("/me/external-identities")
    const verify = await screen.findByRole("button", { name: "验证 ONES" })
    await waitFor(() => expect(verify).toBeEnabled())
    verify.focus()
    expect(verify).toHaveFocus()
    expect(verify).toHaveAttribute("type", "button")

    fireEvent.click(verify)
    expect(await screen.findByLabelText("ONES 邮箱")).toBeVisible()
    expect(screen.getByLabelText("一次性验证密码")).toBeVisible()
    expect(screen.getByRole("button", { name: "验证并读取 Team" })).toHaveAttribute(
      "type",
      "submit"
    )
    expect(screen.getByRole("dialog")).toHaveClass("w-full")
  })
})
