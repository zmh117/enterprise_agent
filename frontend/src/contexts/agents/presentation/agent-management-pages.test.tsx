import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import {
  AgentListPage,
  ModelConnectionPage,
} from "@/contexts/agents/presentation/agent-management-pages"

function json(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      headers: { "Content-Type": "application/json" },
    })
  )
}

function renderWithQuery(children: React.ReactNode, path = "/") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })
      }
    >
      <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

afterEach(() => vi.restoreAllMocks())

describe("Agent management pages", () => {
  it("keeps a large multi-Agent list keyboard navigable", async () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 375,
    })
    const agents = Array.from({ length: 80 }, (_, index) => ({
      id: `agent-${index}`,
      code: `agent-${index}`,
      name: `Agent ${index}`,
      description: "",
      project_code: "default",
      status: index % 2 ? "enabled" : "disabled",
      revision: 1,
      current_publication: {
        id: `publication-${index}`,
        revision: 1,
        config_hash: `hash-${index}`,
      },
      model_connection_status: "ready",
      active_application_count: index % 3,
    }))
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      json({ agents, permissions: { can_create: false } })
    )

    renderWithQuery(<AgentListPage />)

    expect(
      await screen.findByRole("heading", { name: "Agent Publication" })
    ).toBeInTheDocument()
    const links = await screen.findAllByRole("link", { name: /^Agent / })
    expect(links).toHaveLength(80)
    links[79].focus()
    expect(links[79]).toHaveFocus()
    expect(screen.getAllByText("已停用").length).toBeGreaterThan(0)
  })

  it("hides credential writes and full provider addresses without Secret permission", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      json({
        connection: {
          id: "model-connection-1",
          code: "default-deepseek-anthropic",
          name: "DeepSeek",
          status: "enabled",
          revision: 3,
          current_revision_id: "model-revision-3",
          current_revision: {
            id: "model-revision-3",
            revision: 3,
            status: "ready",
            config_hash: "safe-hash",
            provider_host: "api.deepseek.com",
            config: {
              schema_version: 1,
              protocol: "anthropic_compatible",
              model: "deepseek-chat",
              default_opus_model: "deepseek-chat",
              default_sonnet_model: "deepseek-chat",
              default_haiku_model: "deepseek-chat",
              subagent_model: "deepseek-chat",
              effort_level: "max",
            },
            credential: { configured: true, rotation_required: false },
          },
          revisions: [],
          permissions: {
            can_edit: true,
            can_manage_credential: false,
            can_test: false,
          },
        },
      })
    )

    renderWithQuery(
      <Routes>
        <Route
          path="/agent-profiles/:agentCode/model-connections/:connectionCode"
          element={<ModelConnectionPage />}
        />
      </Routes>,
      "/agent-profiles/agent-a/model-connections/default-deepseek-anthropic"
    )

    await waitFor(() =>
      expect(screen.getByText("api.deepseek.com")).toBeInTheDocument()
    )
    expect(screen.queryByLabelText("新 API Key")).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "运行短时测试" })
    ).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain("https://")
    expect(document.body.textContent).not.toContain("secret://")
  })
})
