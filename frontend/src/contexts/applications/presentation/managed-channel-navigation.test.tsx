import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import { resolveActiveNavigationHref } from "@/app/navigation/navigation-match"
import { PlatformNavigation } from "@/app/navigation/platform-navigation"
import { SidebarProvider } from "@/components/ui/sidebar"
import { ManagedChannelsPage } from "@/contexts/applications/presentation/managed-channels-page"
import { AuthenticatedUserProvider } from "@/contexts/auth/presentation/authenticated-user-context"
import { navigationGroups } from "@/mocks/dashboard"

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

function renderWithQuery(ui: React.ReactNode, initialEntries: string[]) {
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

describe("Managed channel navigation", () => {
  it("places channels after the application list and resolves one active entry", () => {
    const group = navigationGroups.find((item) => item.label === "业务应用")
    expect(group?.items.map((item) => item.label)).toEqual([
      "应用列表",
      "渠道与触发器",
    ])
    expect(
      resolveActiveNavigationHref("/applications/channels", group?.items ?? [])
    ).toBe("/applications/channels")
    expect(
      resolveActiveNavigationHref(
        "/applications/default-diagnostic-application",
        group?.items ?? []
      )
    ).toBe("/applications")
  })

  it("highlights only channels on the independent channel route", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
      String(input).endsWith("/api/admin/capabilities")
        ? response({
            capabilities: ["applications.read", "channels.read"],
            modules: {},
          })
        : response({ count: 0 })
    )
    renderWithQuery(
      <AuthenticatedUserProvider user={currentUser}>
        <SidebarProvider>
          <PlatformNavigation />
        </SidebarProvider>
      </AuthenticatedUserProvider>,
      ["/applications/channels"]
    )

    expect(
      await screen.findByRole("link", { name: "渠道与触发器" })
    ).toHaveAttribute("data-active")
    expect(screen.getByRole("link", { name: "应用列表" })).not.toHaveAttribute(
      "data-active",
      "true"
    )
  })

  it("loads the standalone page without requesting a business application", async () => {
    const urls: string[] = []
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      urls.push(url)
      if (url.endsWith("/webhook-connector-options")) {
        return response({
          items: [
            {
              id: "connector-grafana",
              name: "Grafana 告警入口",
              connector_type: "grafana_alert",
              revision: 1,
            },
          ],
        })
      }
      return response({ items: [] })
    })

    renderWithQuery(
      <Routes>
        <Route
          path="/applications/channels"
          element={<ManagedChannelsPage />}
        />
      </Routes>,
      ["/applications/channels"]
    )

    expect(
      await screen.findByRole("heading", { name: "渠道与触发器" })
    ).toBeInTheDocument()
    expect(
      screen.getByText(/此页面不会直接修改任何业务应用/)
    ).toBeInTheDocument()
    await waitFor(() => expect(urls).toHaveLength(3))
    expect(urls).toContain("/api/admin/managed-channels")
    expect(urls).toContain(
      "/api/admin/managed-channels/dingtalk-enterprises"
    )
    expect(urls).toContain(
      "/api/admin/managed-channels/webhook-connector-options"
    )
    expect(urls.some((url) => url.includes("business-applications"))).toBe(
      false
    )
  })
})
