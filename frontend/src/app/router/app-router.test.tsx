import { act, render, screen } from "@testing-library/react"
import { RouterProvider } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const pageLoads = vi.hoisted(() => {
  let release = () => {}
  const ready = new Promise<void>((resolve) => {
    release = resolve
  })
  return {
    capabilities: [] as string[],
    checking: false,
    dashboard: vi.fn(),
    ready,
    release,
  }
})

vi.mock("@/app/shell/platform-shell", async () => {
  const { Outlet } = await import("react-router-dom")
  return {
    PlatformShell: () => (
      <>
        <nav aria-label="平台导航">平台导航</nav>
        <Outlet />
      </>
    ),
  }
})

vi.mock("@/contexts/auth/application/admin-capability-query", () => ({
  useAdminCapabilitySummary: () => ({
    isLoading: pageLoads.checking,
    isError: false,
    error: null,
    data: { capabilities: pageLoads.capabilities, modules: {} },
    refetch: vi.fn(),
  }),
}))

vi.mock("@/contexts/overview/presentation/dashboard-page", async () => {
  pageLoads.dashboard()
  await pageLoads.ready
  return { DashboardPage: () => <h1>合成工作台</h1> }
})

vi.mock(
  "@/contexts/platform-governance/presentation/tool-resources-page",
  () => ({
    ToolResourcesPage: () => <h1>合成资源页面</h1>,
  })
)

vi.mock("@/contexts/external-identities", () => ({
  MyExternalIdentitiesPage: () => <h1>合成个人身份页面</h1>,
}))

vi.mock(
  "@/contexts/applications/presentation/application-detail-page",
  async () => {
    throw new Error("合成页面块加载失败")
  }
)

import { appRouter } from "@/app/router/app-router"

beforeEach(async () => {
  pageLoads.capabilities = []
  pageLoads.checking = false
  await appRouter.navigate("/")
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("管理路由延迟加载", () => {
  it("权限校验期间不加载目标页面", async () => {
    pageLoads.checking = true
    render(<RouterProvider router={appRouter} />)

    expect(await screen.findByText("正在校验页面权限…")).toBeInTheDocument()
    expect(pageLoads.dashboard).not.toHaveBeenCalled()
    expect(screen.queryByText("正在加载管理页面…")).not.toBeInTheDocument()
  })

  it("无权限时保留拒绝页面且不加载目标模块", async () => {
    render(<RouterProvider router={appRouter} />)

    expect(await screen.findByText("无权访问此页面")).toBeInTheDocument()
    expect(pageLoads.dashboard).not.toHaveBeenCalled()
  })

  it("获准后展示中文加载状态，完成加载并可导航到另一页面", async () => {
    pageLoads.capabilities = ["dashboard.read", "platform.read"]
    render(<RouterProvider router={appRouter} />)

    expect(await screen.findByRole("status")).toHaveTextContent(
      "正在加载管理页面…"
    )
    expect(
      screen.getByRole("navigation", { name: "平台导航" })
    ).toBeInTheDocument()
    pageLoads.release()
    expect(
      await screen.findByRole("heading", { name: "合成工作台" })
    ).toBeInTheDocument()

    await act(() => appRouter.navigate("/platform/resources"))
    expect(
      await screen.findByRole("heading", { name: "合成资源页面" })
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("heading", { name: "合成工作台" })
    ).not.toBeInTheDocument()
  })

  it("个人身份页面保留原有路由和权限边界", async () => {
    await appRouter.navigate("/me/external-identities")
    render(<RouterProvider router={appRouter} />)

    expect(
      await screen.findByRole("heading", { name: "合成个人身份页面" })
    ).toBeInTheDocument()
    expect(screen.queryByText("无权访问此页面")).not.toBeInTheDocument()
  })

  it("模块导入失败进入现有刷新与返回入口", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {})
    pageLoads.capabilities = ["applications.read"]
    await appRouter.navigate("/applications/synthetic")
    render(<RouterProvider router={appRouter} />)

    expect(
      await screen.findByRole("heading", { name: "管理页面暂时无法显示" })
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "刷新页面" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "返回工作台" })).toHaveAttribute(
      "href",
      "/"
    )
  })
})
