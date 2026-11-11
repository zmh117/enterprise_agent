import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CreateCodeResource, CodeResourceEditor } from "./code-resource-editor"
import { knowledgeResourceSchema } from "../domain/knowledge-resource"
import { changeKnowledgeResource } from "../infrastructure/knowledge-resource-api"

afterEach(() => vi.unstubAllGlobals())
const resource = knowledgeResourceSchema.parse({
  id: "code-resource",
  knowledge_base_id: "code-kb",
  kind: "code",
  code: "code-library",
  name: "代码库",
  revision: 2,
  status: "enabled",
  draft: {
    id: "draft",
    revision: 1,
    binding_id: null,
    index_id: null,
    config_hash: "a".repeat(64),
    code_configuration: {
      source_id: null,
      checkout_id: null,
      svn_access_ref: null,
      allowed_paths_json: [],
    },
  },
  published: null,
  verification: null,
})

describe("代码知识库配置", () => {
  it("创建空代码库不需要先选已有内容或 ONES 身份", async () => {
    const execute = vi.fn(async () => true)
    render(<CreateCodeResource pending={false} execute={execute} />)
    fireEvent.change(screen.getByTestId("code-kb-name"), {
      target: { value: "工单规则" },
    })
    fireEvent.change(screen.getByTestId("code-kb-code"), {
      target: { value: "order-rules" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建代码知识库" }))
    await waitFor(() =>
      expect(execute).toHaveBeenCalledWith({
        kind: "create-code",
        input: { name: "工单规则", code: "order-rules" },
      })
    )
    expect(screen.queryByText(/Team|本人 ONES|已登记源码快照/)).toBeNull()
  })

  it("目录选择保留范围并保存资源绑定，未初始化索引不能验证或发布", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async (input) =>
          new Response(
            JSON.stringify(
              String(input).includes("/api/platform/environments")
                ? {
                    environments: [
                      {
                        id: "env-one",
                        code: "one",
                        display_name: "环境一",
                        status: "enabled",
                        revision: 1,
                      },
                      {
                        id: "env-two",
                        code: "two",
                        display_name: "环境二",
                        status: "enabled",
                        revision: 1,
                      },
                    ],
                  }
                : String(input).endsWith("/index-status")
                  ? { paused: false, indexes: [] }
                  : {
                      enabled: true,
                      registrations: [
                        {
                          id: "local-svn",
                          url: "https://svn.invalid/trunk",
                          kind: "deployment",
                        },
                        {
                          id: "duplicate-account",
                          url: "https://svn.invalid/trunk",
                          kind: "account",
                        },
                      ],
                      jobs: [],
                      checkouts: [
                        {
                          id: "checkout",
                          source_id: "source",
                          relative_dir: "mes",
                          state: "ready",
                          verified_revision: 100,
                          generation: 2,
                          writer_operation_id: null,
                          readers: 2,
                          selected_paths: ["set_server", "set_web/JTH"],
                          connection: {
                            id: "local-svn",
                            url: "https://original.invalid/trunk",
                            kind: "account",
                          },
                          connection_error: null,
                        },
                        {
                          id: "other-checkout",
                          source_id: "other-source",
                          relative_dir: "other-project",
                          state: "ready",
                          verified_revision: 2,
                          generation: 1,
                          writer_operation_id: null,
                          readers: 0,
                          selected_paths: [""],
                          connection: {
                            id: "anonymous-svn",
                            url: "https://other.invalid/trunk",
                            kind: "anonymous",
                          },
                          connection_error: null,
                        },
                      ],
                    }
            ),
            { headers: { "Content-Type": "application/json" } }
          )
      )
    )
    const execute = vi.fn(async () => true)
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CodeResourceEditor
          resource={resource}
          canManage
          pending={false}
          execute={execute}
          reload={async () => {}}
        />
      </QueryClientProvider>
    )
    await screen.findByRole("option", { name: /mes · SVN r100 · 2 个读取任务/ })
    fireEvent.change(screen.getByTestId("code-kb-checkout"), {
      target: { value: "checkout" },
    })
    expect(screen.getByTestId("code-kb-paths")).toHaveValue(
      "set_server\nset_web/JTH"
    )
    fireEvent.click(await screen.findByTestId("code-kb-environment-one"))
    fireEvent.click(screen.getByTestId("code-kb-environment-two"))
    fireEvent.click(screen.getByRole("button", { name: "保存源码配置" }))
    await waitFor(() =>
      expect(execute).toHaveBeenCalledWith({
        kind: "code-draft",
        id: "code-resource",
        input: {
          expected_revision: 2,
          checkout_id: "checkout",
          environment_ids: ["env-one", "env-two"],
          allowed_paths: ["set_server", "set_web/JTH"],
        },
      })
    )
    expect(screen.getByRole("button", { name: "验证草稿" })).toBeDisabled()
    expect(screen.queryByLabelText("SVN 访问登记")).toBeNull()
    expect(screen.getByTestId("code-kb-checkout-connection")).toHaveTextContent(
      "https://original.invalid/trunk"
    )
    expect(screen.getByTestId("code-kb-checkout-connection")).toHaveTextContent(
      "用户名密码（已保存）"
    )
    expect(
      screen.getByRole("button", { name: "发布代码知识库" })
    ).toBeDisabled()
    expect(
      screen.queryByText(/已登记源码快照|基线提取|提取应用|执行服务账号/)
    ).toBeNull()
    fireEvent.change(screen.getByTestId("code-kb-checkout"), {
      target: { value: "other-checkout" },
    })
    expect(screen.getByTestId("code-kb-checkout-connection")).toHaveTextContent(
      "https://other.invalid/trunk"
    )
    expect(screen.getByTestId("code-kb-checkout-connection")).toHaveTextContent(
      "无需认证"
    )
    expect(
      screen.getByTestId("code-kb-checkout-connection")
    ).not.toHaveTextContent("https://original.invalid/trunk")
  })

  it.each([
    ["CODE_CHECKOUT_CONNECTION_UNAVAILABLE", /无法确认该目录的原始 SVN 连接/],
    ["CODE_REGISTRATION_CHANGED", /SVN 连接不属于当前知识库/],
  ])(
    "目录连接 %s 时禁选，既有绑定显示原因且阻止保存",
    async (code, message) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(
          async (input) =>
            new Response(
              JSON.stringify(
                String(input).includes("/api/platform/environments")
                  ? { environments: [] }
                  : String(input).endsWith("/index-status")
                    ? { paused: false, indexes: [] }
                    : {
                        enabled: true,
                        registrations: [],
                        jobs: [],
                        checkouts: [
                          {
                            id: "missing-connection",
                            source_id: "source",
                            relative_dir: "legacy",
                            state: "ready",
                            verified_revision: 2,
                            generation: 1,
                            writer_operation_id: null,
                            readers: 0,
                            selected_paths: [""],
                            connection: null,
                            connection_error: code,
                          },
                        ],
                      }
              ),
              { headers: { "Content-Type": "application/json" } }
            )
        )
      )
      const execute = vi.fn(async () => true)
      render(
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <CodeResourceEditor
            resource={{
              ...resource,
              draft: {
                ...resource.draft!,
                code_configuration: {
                  ...resource.draft!.code_configuration!,
                  checkout_id: "missing-connection",
                },
              },
            }}
            canManage
            pending={false}
            execute={execute}
            reload={async () => {}}
          />
        </QueryClientProvider>
      )
      expect(
        await screen.findByRole("option", {
          name: /legacy · SVN r2.*当前知识库不可用/,
        })
      ).toBeDisabled()
      expect(screen.getByText(message)).toBeInTheDocument()
      expect(
        screen.getByRole("button", { name: "保存源码配置" })
      ).toBeDisabled()
      expect(execute).not.toHaveBeenCalled()
    }
  )

  it("代码创建使用独立类型端点，空索引 ID 可解析", async () => {
    const fetch = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(
      async () =>
        new Response(JSON.stringify(resource), {
          headers: { "Content-Type": "application/json" },
        })
    )
    vi.stubGlobal("fetch", fetch)
    expect(
      await changeKnowledgeResource({
        kind: "create-code",
        input: { code: "code-library", name: "代码库" },
      })
    ).toMatchObject({ kind: "code", draft: { index_id: null } })
    expect(fetch.mock.calls[0]?.[0]).toBe(
      "/api/platform/knowledge/code-resources"
    )
  })
})
