import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import {
  AgentProfilePage,
  AgentProfilesPage,
} from "@/contexts/agent-profiles/presentation/agent-profile-page"

function response(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  )
}

const config = {
  business_role: "诊断助手",
  business_instructions: "只读诊断",
  model_policy: {
    runtime: "claude_agent_sdk",
    model: "deepseek-v4-flash",
    model_connection_revision_id: "model_revision_1",
  },
  execution: { max_turns: 12, timeout_seconds: 300 },
  tools: ["get_er_context"],
  skills: [],
  routing: { project_code: "default" },
  channels: {
    ingress: ["connector-dingtalk-stream-default"],
    delivery: ["connector-dingtalk-stream-default"],
  },
}

describe("Agent Profile management", () => {
  it("renders the Profile list from the management API", async () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(
      response({
        agents: [
          {
            id: "agent_1",
            code: "default-diagnostic-agent",
            name: "默认诊断 Agent",
            description: "",
            project_code: "default",
            status: "enabled",
            revision: 2,
            management_mode: "editable",
            current_publication: {
              id: "agent_publication_1",
              revision: 3,
              config_hash: "publication-hash",
            },
            model_connection_status: "ready",
            active_application_count: 1,
          },
        ],
      })
    )

    render(
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false } },
          })
        }
      >
        <MemoryRouter>
          <AgentProfilesPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(await screen.findByText("默认诊断 Agent")).toBeInTheDocument()
    expect(screen.getByText("r3")).toBeInTheDocument()
    expect(screen.getByText("已就绪")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "进入配置" })).toHaveAttribute(
      "href",
      "/agent-profiles/default-diagnostic-agent"
    )
  })

  it("shows the saved model connection without exposing a raw credential", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input) => {
        const url = String(input)
        if (url.endsWith("/test")) {
          return response({
            result: {
              success: true,
              connection_revision_id: "model_revision_1",
              provider_host: "api.deepseek.com",
              model: "deepseek-v4-flash",
              duration_ms: 82,
              runtime: "claude_agent_sdk",
              detail: "Connection succeeded",
            },
          })
        }
        if (url.includes("/model-connections/")) {
          return response({
            connection: {
              id: "model_connection_1",
              code: "default-deepseek-anthropic",
              name: "默认 DeepSeek Anthropic 连接",
              protocol: "anthropic_compatible",
              status: "ready",
              revision: 1,
              current_revision_id: "model_revision_1",
              created_at: "2026-07-25T00:00:00+08:00",
              updated_at: "2026-07-25T00:00:00+08:00",
              current_revision: {
                id: "model_revision_1",
                connection_id: "model_connection_1",
                connection_code: "default-deepseek-anthropic",
                revision: 1,
                status: "ready",
                config: {
                  schema_version: 1,
                  protocol: "anthropic_compatible",
                  base_url: "https://api.deepseek.com/anthropic",
                  model: "deepseek-v4-flash",
                  default_opus_model: "deepseek-v4-flash",
                  default_sonnet_model: "deepseek-v4-flash",
                  default_haiku_model: "deepseek-v4-flash",
                  subagent_model: "deepseek-v4-flash",
                  effort_level: "max",
                },
                config_hash: "hash",
                provider_host: "api.deepseek.com",
                credential: {
                  configured: true,
                  masked: "sk-****1234",
                  version: 2,
                  updated_at: "2026-07-25T00:00:00+08:00",
                  rotation_required: false,
                },
                created_by: "user_local_admin",
                created_at: "2026-07-25T00:00:00+08:00",
              },
              revisions: [],
            },
          })
        }
        if (url.endsWith("/publications")) {
          return response({
            publications: [
              {
                id: "agent_publication_1",
                revision: 1,
                config_hash: "publication-hash",
                snapshot: config,
                published_at: "2026-07-25T00:00:00+08:00",
                published_by: "user_local_admin",
                model_runtime_mode: "pinned_connection",
                active_applications: [],
              },
              {
                id: "agent_publication_0",
                revision: 0,
                config_hash: "legacy-publication-hash",
                snapshot: config,
                published_at: "2026-07-24T00:00:00+08:00",
                published_by: "user_local_admin",
                model_runtime_mode: "legacy_global_connection",
                active_applications: [
                  {
                    code: "default-diagnostic-application",
                    name: "默认诊断应用",
                    environment: "local",
                    application_publication_id: "business_publication_1",
                    href: "/applications/default-diagnostic-application",
                  },
                ],
              },
            ],
          })
        }
        if (url.endsWith("/publish") || url.endsWith("/rollback")) {
          return response({
            publication: {
              id: "agent_publication_1",
              revision: 1,
              config_hash: "publication-hash",
              snapshot: config,
              published_at: "2026-07-25T00:00:00+08:00",
              published_by: "user_local_admin",
            },
          })
        }
        return response({
          agent: {
            definition: {
              id: "agent_1",
              code: "default-diagnostic-agent",
              name: "默认诊断 Agent",
              description: "",
              project_code: "default",
              status: "enabled",
              revision: 2,
              current_publication_id: "agent_publication_1",
            },
            draft: {
              id: "agent_revision_2",
              revision: 2,
              status: "validated",
              config_hash: "agent-hash",
              config,
              validation: { valid: true, errors: [] },
              created_at: "2026-07-25T00:00:00+08:00",
              updated_at: "2026-07-25T00:00:00+08:00",
            },
            current_publication: {
              id: "agent_publication_1",
              revision: 1,
              config_hash: "publication-hash",
              snapshot: config,
              published_at: "2026-07-25T00:00:00+08:00",
              published_by: "user_local_admin",
            },
            permissions: {
              can_edit_profile: true,
              can_publish: true,
              can_manage_credential: true,
              can_test_connection: true,
            },
            catalog: {
              models: ["deepseek-v4-flash"],
              tools: ["get_er_context"],
              skills: [],
              connectors: [
                {
                  id: "connector-dingtalk-stream-default",
                  connector_type: "dingtalk",
                  name: "DingTalk",
                  enabled: 1,
                  allow_ingress: 1,
                  allow_delivery: 1,
                },
              ],
            },
          },
        })
      })

    render(
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
        <MemoryRouter>
          <AgentProfilePage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    expect(await screen.findByText("默认诊断 Agent")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("tab", { name: "模型连接" }))
    expect(
      await screen.findByDisplayValue("https://api.deepseek.com/anthropic")
    ).toBeInTheDocument()
    expect(screen.getByText("sk-****1234")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "测试已保存版本" }))
    expect(
      await screen.findByText(
        "连接成功 · api.deepseek.com · deepseek-v4-flash · 82ms"
      )
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "轮换 API Key" }))
    const keyInput = screen.getByPlaceholderText("输入新的 API Key")
    expect(keyInput).toHaveValue("")
    fireEvent.change(keyInput, { target: { value: crypto.randomUUID() } })
    fireEvent.click(screen.getByRole("button", { name: "关闭" }))
    fireEvent.click(screen.getByRole("button", { name: "轮换 API Key" }))
    expect(screen.getByPlaceholderText("输入新的 API Key")).toHaveValue("")
    fireEvent.click(screen.getByRole("button", { name: "关闭" }))

    fireEvent.click(screen.getByRole("tab", { name: "Agent 配置" }))
    fireEvent.click(screen.getByRole("button", { name: "发布 Agent" }))
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/agents/default-diagnostic-agent/publish",
        expect.objectContaining({ method: "POST" })
      )
    )

    fireEvent.click(screen.getByRole("tab", { name: "发布历史" }))
    expect(
      await screen.findByRole("link", { name: "默认诊断应用 · local" })
    ).toHaveAttribute("href", "/applications/default-diagnostic-application")
    const rollbackButtons = screen.getAllByRole("button", {
      name: "回退 Agent",
    })
    const enabledRollback = rollbackButtons.find(
      (button) => !button.hasAttribute("disabled")
    )
    expect(enabledRollback).toBeDefined()
    fireEvent.click(enabledRollback!)
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/agents/default-diagnostic-agent/rollback",
        expect.objectContaining({ method: "POST" })
      )
    )
    expect(document.body.textContent).not.toContain("secret://platform/")
  })
})
