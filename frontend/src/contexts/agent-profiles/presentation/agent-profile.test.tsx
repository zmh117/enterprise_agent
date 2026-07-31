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

function errorResponse(status: number, detail: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify({ detail }), {
      status,
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

const modelConfig = {
  schema_version: 1,
  protocol: "anthropic_compatible" as const,
  base_url: "https://api.deepseek.com/anthropic",
  model: "deepseek-v4-flash",
  default_opus_model: "deepseek-v4-flash",
  default_sonnet_model: "deepseek-v4-flash",
  default_haiku_model: "deepseek-v4-flash",
  subagent_model: "deepseek-v4-flash",
  effort_level: "max" as const,
}

const modelRevision = {
  id: "model_revision_1",
  connection_id: "model_connection_1",
  connection_code: "default-deepseek-anthropic",
  revision: 1,
  status: "ready",
  config: modelConfig,
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
}

const modelConnection = {
  id: "model_connection_1",
  code: "default-deepseek-anthropic",
  name: "默认 DeepSeek Anthropic 连接",
  protocol: "anthropic_compatible",
  status: "ready",
  revision: 1,
  current_revision_id: "model_revision_1",
  created_at: "2026-07-25T00:00:00+08:00",
  updated_at: "2026-07-25T00:00:00+08:00",
  current_revision: modelRevision,
  revisions: [],
}

function agentPayload(
  permissions: Partial<{
    can_edit_profile: boolean
    can_publish: boolean
    can_manage_credential: boolean
    can_test_connection: boolean
  }> = {}
) {
  return {
    agent: {
      definition: {
        id: "agent_1",
        code: "default-diagnostic-agent",
        name: "默认诊断 Agent",
        description: "",
        project_code: "default",
        status: "enabled",
        revision: 2,
        current_publication_id: null,
      },
      draft: {
        id: "agent_revision_2",
        revision: 2,
        status: "draft",
        config_hash: "agent-hash",
        config,
        validation: {},
        created_at: "2026-07-25T00:00:00+08:00",
        updated_at: "2026-07-25T00:00:00+08:00",
      },
      current_publication: null,
      permissions: {
        can_edit_profile: true,
        can_publish: true,
        can_manage_credential: true,
        can_test_connection: true,
        ...permissions,
      },
      catalog: {
        models: [modelConfig.model],
        tools: [],
        skills: [],
        connectors: [],
      },
    },
  }
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
            model_connection_status: "missing_revision",
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
    expect(screen.getByText("引用版本已删除，请重新配置")).toBeInTheDocument()
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
        if (url.endsWith("/discover")) {
          return response({
            result: {
              provider_host: "api.deepseek.com",
              normalized_base_url: modelConfig.base_url,
              models: [
                {
                  id: "deepseek-v4-flash",
                  display_name: "deepseek-v4-flash",
                },
                {
                  id: "deepseek-reasoner",
                  display_name: "deepseek-reasoner",
                },
              ],
              duration_ms: 32,
              credential_source: "existing",
            },
          })
        }
        if (url.endsWith("/test-draft")) {
          return response({
            result: {
              success: true,
              provider_host: "api.deepseek.com",
              model: "deepseek-v4-flash",
              duration_ms: 82,
              runtime: "claude_agent_sdk",
              detail: "连接成功",
            },
          })
        }
        if (url.endsWith("/configure")) {
          return response({
            revision: {
              ...modelRevision,
              id: "model_revision_2",
              revision: 2,
            },
          })
        }
        if (url.includes("/model-connections/")) {
          return response({ connection: modelConnection })
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
    expect(
      screen.getByRole("combobox", { name: "Credential 来源" })
    ).toHaveValue("existing")
    fireEvent.click(screen.getByRole("button", { name: "发现可用模型" }))
    expect(await screen.findByRole("combobox", { name: "主模型" })).toHaveValue(
      "deepseek-v4-flash"
    )
    fireEvent.click(screen.getByRole("button", { name: "测试当前配置" }))
    expect(
      await screen.findByText(
        "连接成功 · api.deepseek.com · deepseek-v4-flash · 82ms"
      )
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "验证并原子保存" })).toBeEnabled()

    fireEvent.change(screen.getByRole("combobox", { name: "推理强度" }), {
      target: { value: "high" },
    })
    expect(
      screen.queryByText(
        "连接成功 · api.deepseek.com · deepseek-v4-flash · 82ms"
      )
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "验证并原子保存" })
    ).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "测试当前配置" }))
    await screen.findByText(
      "连接成功 · api.deepseek.com · deepseek-v4-flash · 82ms"
    )
    fireEvent.click(screen.getByRole("button", { name: "验证并原子保存" }))
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/admin/model-connections/default-deepseek-anthropic/configure",
        expect.objectContaining({ method: "PUT" })
      )
    )
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        /\/(revision|credential|test)$/.test(String(input))
      )
    ).toBe(false)

    fireEvent.change(
      screen.getByRole("combobox", { name: "Credential 来源" }),
      { target: { value: "submitted" } }
    )
    const rotationKey = screen.getByPlaceholderText("输入 DeepSeek API Key")
    fireEvent.change(rotationKey, { target: { value: "rotate-plaintext-key" } })
    fireEvent.change(
      screen.getByRole("textbox", { name: "服务地址（Base URL）" }),
      { target: { value: `${modelConfig.base_url}/` } }
    )
    expect(rotationKey).toHaveValue("")
    fireEvent.change(rotationKey, { target: { value: "rotate-plaintext-key" } })
    fireEvent.click(screen.getByRole("button", { name: "发现可用模型" }))
    await screen.findByRole("combobox", { name: "主模型" })
    fireEvent.click(screen.getByRole("button", { name: "测试当前配置" }))
    await screen.findByText(
      "连接成功 · api.deepseek.com · deepseek-v4-flash · 82ms"
    )
    fireEvent.click(screen.getByRole("button", { name: "验证并原子保存" }))
    await waitFor(() => expect(rotationKey).toHaveValue(""))
    const configureBodies = fetchSpy.mock.calls
      .filter(([input]) => String(input).endsWith("/configure"))
      .map(([, init]) => JSON.parse(String(init?.body)))
    expect(configureBodies).toContainEqual(
      expect.objectContaining({
        credential_source: "submitted",
        api_key: "rotate-plaintext-key",
      })
    )

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

  it("allows rebuilding model configuration after every revision was reset", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input) => {
        const url = String(input)
        if (url.endsWith("/discover")) {
          return response({
            result: {
              provider_host: "api.deepseek.com",
              normalized_base_url: modelConfig.base_url,
              models: [
                {
                  id: "deepseek-v4-flash",
                  display_name: "deepseek-v4-flash",
                },
              ],
              duration_ms: 30,
              credential_source: "submitted",
            },
          })
        }
        if (url.endsWith("/test-draft")) {
          return response({
            result: {
              success: true,
              provider_host: "api.deepseek.com",
              model: "deepseek-v4-flash",
              duration_ms: 80,
              runtime: "claude_agent_sdk",
              detail: "连接成功",
            },
          })
        }
        if (url.endsWith("/configure")) {
          return response({
            revision: {
              ...modelRevision,
              revision: 1,
              credential: {
                ...modelRevision.credential,
                version: 1,
              },
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
              status: "rotation_required",
              revision: 0,
              current_revision_id: "",
              created_at: "2026-07-25T00:00:00+08:00",
              updated_at: "2026-07-29T00:00:00+08:00",
              current_revision: null,
              revisions: [],
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
              revision: 29,
              current_publication_id: "agent_publication_29",
            },
            draft: {
              id: "agent_revision_29",
              revision: 29,
              status: "published",
              config_hash: "agent-hash",
              config,
              validation: { valid: true, errors: [] },
              created_at: "2026-07-25T00:00:00+08:00",
              updated_at: "2026-07-25T00:00:00+08:00",
            },
            current_publication: {
              id: "agent_publication_29",
              revision: 29,
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
              connectors: [],
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
      screen.getByRole("textbox", { name: "服务地址（Base URL）" })
    ).toBeInTheDocument()
    const discover = screen.getByRole("button", { name: "发现可用模型" })
    expect(discover).toBeDisabled()
    const keyInput = screen.getByPlaceholderText("输入 DeepSeek API Key")
    const plaintext = crypto.randomUUID()
    fireEvent.change(keyInput, { target: { value: plaintext } })
    expect(discover).toBeEnabled()
    fireEvent.click(discover)
    const mainModel = await screen.findByRole("combobox", { name: "主模型" })
    fireEvent.change(mainModel, { target: { value: "deepseek-v4-flash" } })
    fireEvent.click(screen.getByRole("button", { name: "测试当前配置" }))
    await screen.findByText(
      "连接成功 · api.deepseek.com · deepseek-v4-flash · 80ms"
    )
    fireEvent.click(screen.getByRole("button", { name: "验证并原子保存" }))
    await waitFor(() => expect(keyInput).toHaveValue(""))
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        /\/(revision|credential|test)$/.test(String(input))
      )
    ).toBe(false)
    const configureCall = fetchSpy.mock.calls.find(([input]) =>
      String(input).endsWith("/configure")
    )
    expect(configureCall).toBeDefined()
    expect(JSON.parse(String(configureCall?.[1]?.body))).toEqual(
      expect.objectContaining({ expected_revision: 0, api_key: plaintext })
    )
  })

  it("uses one current revision and resets the wizard after a configure conflict", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input) => {
        const url = String(input)
        if (url.endsWith("/discover")) {
          return response({
            result: {
              provider_host: "api.deepseek.com",
              normalized_base_url: modelConfig.base_url,
              models: [
                {
                  id: modelConfig.model,
                  display_name: modelConfig.model,
                },
              ],
              duration_ms: 20,
              credential_source: "existing",
            },
          })
        }
        if (url.endsWith("/test-draft")) {
          return response({
            result: {
              success: true,
              provider_host: "api.deepseek.com",
              model: modelConfig.model,
              duration_ms: 50,
              runtime: "claude_agent_sdk",
              detail: "连接成功",
            },
          })
        }
        if (url.endsWith("/configure")) {
          return errorResponse(409, {
            message: "模型连接已发生变化，请刷新后重新检测",
            code: "revision_conflict",
            field_errors: [],
            current_revision: 2,
          })
        }
        if (url.includes("/model-connections/")) {
          return response({ connection: modelConnection })
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
              current_publication_id: null,
            },
            draft: {
              id: "agent_revision_2",
              revision: 2,
              status: "draft",
              config_hash: "agent-hash",
              config,
              validation: {},
              created_at: "2026-07-25T00:00:00+08:00",
              updated_at: "2026-07-25T00:00:00+08:00",
            },
            current_publication: null,
            permissions: {
              can_edit_profile: true,
              can_publish: true,
              can_manage_credential: true,
              can_test_connection: true,
            },
            catalog: {
              models: [modelConfig.model],
              tools: [],
              skills: [],
              connectors: [],
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
    fireEvent.click(screen.getByRole("button", { name: "发现可用模型" }))
    await screen.findByRole("combobox", { name: "主模型" })
    fireEvent.click(screen.getByRole("button", { name: "测试当前配置" }))
    await screen.findByText(
      "连接成功 · api.deepseek.com · deepseek-v4-flash · 50ms"
    )
    fireEvent.click(screen.getByRole("button", { name: "验证并原子保存" }))
    expect(
      await screen.findByText("模型连接已发生变化，请刷新后重新检测")
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("combobox", { name: "主模型" })
    ).not.toBeInTheDocument()
    const configureCall = fetchSpy.mock.calls.find(([input]) =>
      String(input).endsWith("/configure")
    )
    expect(JSON.parse(String(configureCall?.[1]?.body))).toEqual(
      expect.objectContaining({
        expected_revision: 1,
        credential_source: "existing",
        api_key: "",
      })
    )
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        /\/(revision|credential|test)$/.test(String(input))
      )
    ).toBe(false)
  })

  it("requires reselecting a legacy model that discovery no longer returns", async () => {
    const retiredRevision = {
      ...modelRevision,
      config: {
        ...modelConfig,
        model: "retired-deepseek-model",
        default_opus_model: "retired-deepseek-model",
      },
    }
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/discover")) {
        return response({
          result: {
            provider_host: "api.deepseek.com",
            normalized_base_url: modelConfig.base_url,
            models: [
              {
                id: modelConfig.model,
                display_name: modelConfig.model,
              },
            ],
            duration_ms: 20,
            credential_source: "existing",
          },
        })
      }
      if (url.includes("/model-connections/")) {
        return response({
          connection: {
            ...modelConnection,
            current_revision: retiredRevision,
          },
        })
      }
      return response(agentPayload())
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
    fireEvent.click(screen.getByRole("button", { name: "发现可用模型" }))
    expect(
      await screen.findByText(/历史模型已不可用：retired-deepseek-model/)
    ).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "主模型" })).toHaveValue("")
    expect(
      screen.getByRole("button", { name: "验证并原子保存" })
    ).toBeDisabled()
  })

  it("keeps the unified wizard readable and disabled without permissions", async () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 375,
    })
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/model-connections/")) {
        return response({ connection: modelConnection })
      }
      return response(
        agentPayload({
          can_manage_credential: false,
          can_test_connection: false,
        })
      )
    })

    render(
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false } },
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
    expect(screen.getByText("DeepSeek 模型连接向导")).toBeInTheDocument()
    expect(
      screen.getByText(
        "当前账号需要 Agent 编辑和 Secret 管理权限才能配置模型连接。"
      )
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "发现可用模型" })).toBeDisabled()
  })
})
