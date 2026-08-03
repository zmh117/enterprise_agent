import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PlatformNavigation } from "@/app/navigation/platform-navigation"
import { SidebarProvider } from "@/components/ui/sidebar"
import { AuthenticatedUserProvider } from "@/contexts/auth/presentation/authenticated-user-context"
import { ApiError } from "@/shared/api/api-client"

const currentUser = {
  id: "user-local-admin",
  username: "zmh",
  display_name: "张明浩",
  roles: ["platform-admin"],
  auth_source: "local",
  capabilities: {},
}

function response(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      headers: { "Content-Type": "application/json" },
    })
  )
}

function renderNavigation(logout: () => Promise<void>) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
    String(input).endsWith("/api/admin/capabilities")
      ? response({ capabilities: [], modules: {} })
      : response({ count: 0 })
  )
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AuthenticatedUserProvider user={currentUser} logout={logout}>
          <SidebarProvider>
            <PlatformNavigation />
          </SidebarProvider>
        </AuthenticatedUserProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

async function openLogoutConfirmation() {
  fireEvent.click(
    screen.getByRole("button", { name: "打开 张明浩 的账户菜单" })
  )
  fireEvent.click(await screen.findByRole("menuitem", { name: "退出账户" }))
  expect(
    await screen.findByRole("heading", { name: "退出当前账户？" })
  ).toBeInTheDocument()
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("PlatformNavigation account menu", () => {
  it("replaces the MVP status card and asks for confirmation before logout", async () => {
    const logout = vi.fn().mockResolvedValue(undefined)

    renderNavigation(logout)

    expect(screen.queryByText("MVP 已接线")).not.toBeInTheDocument()
    expect(screen.getByText("张明浩")).toBeInTheDocument()
    expect(screen.getByText("@zmh")).toBeInTheDocument()

    await openLogoutConfirmation()
    expect(logout).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: "确认退出" }))

    await waitFor(() => expect(logout).toHaveBeenCalledOnce())
  })

  it("keeps the confirmation open and reports an error when logout fails", async () => {
    const logout = vi.fn().mockRejectedValue(
      new ApiError({
        status: 0,
        code: "network_unavailable",
        message: "管理服务当前不可用，请稍后重试。",
      })
    )

    renderNavigation(logout)
    await openLogoutConfirmation()
    fireEvent.click(screen.getByRole("button", { name: "确认退出" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "管理服务当前不可用，请稍后重试。"
    )
    expect(
      screen.getByRole("heading", { name: "退出当前账户？" })
    ).toBeInTheDocument()
  })
})
