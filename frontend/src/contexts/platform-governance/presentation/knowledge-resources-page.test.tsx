import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { KnowledgeResourcesPage } from "@/contexts/platform-governance/presentation/knowledge-resources-page"
import { ToolResourcesPage } from "@/contexts/platform-governance/presentation/tool-resources-page"

const hash = "a".repeat(64)
const prefix = "/api/platform/knowledge"
function resource() {
  return {
    id: "res",
    knowledge_base_id: "kb",
    code: "ones-bugs",
    name: "合成缺陷库",
    revision: 1,
    status: "enabled",
    draft: null,
    published: null,
    verification: null,
  }
}
function setup({
  manage = true,
  capsStatus = 200,
  populated = true,
  fail = "",
} = {}) {
  const calls: {
    url: string
    method: string
    body: Record<string, unknown>
  }[] = []
  const state = {
    resources: populated ? [resource()] : [],
    bindings: [
      {
        id: "binding",
        source_id: "source",
        revision: 1,
        instance_code: "default",
        team_id: "team",
        state: "VERIFIED",
      },
    ],
  } as {
    resources: Array<Record<string, unknown>>
    bindings: Array<Record<string, unknown>>
  }
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, options: RequestInit = {}) => {
      const url = String(input),
        method = options.method ?? "GET"
      const body = options.body ? JSON.parse(String(options.body)) : {}
      const reply = (value: unknown, status = 200) =>
        new Response(JSON.stringify(value), {
          status,
          headers: { "Content-Type": "application/json" },
        })
      if (url === "/api/admin/capabilities")
        return reply(
          {
            capabilities: [
              "platform.read",
              ...(manage ? ["platform.manage"] : []),
            ],
            modules: {},
          },
          capsStatus
        )
      if (url === "/api/platform/resources") return reply({ resources: [] })
      if (url === "/api/platform/secrets")
        return reply({
          secrets: [
            {
              id: "synthetic-secret",
              code: "content-reader",
              provider: "platform",
              secret_ref: "secret://platform/content-reader",
              status: "enabled",
              active_version: 1,
              configured: true,
              revision: 1,
            },
          ],
        })
      if (method === "GET") {
        if (url === `${prefix}/sources`)
          return reply({
            sources: [
              {
                id: "source",
                code: "source",
                display_name: "合成离线批次",
                source_system: "ones",
                origin_state: "offline_unverified",
              },
            ],
            bindings: state.bindings,
          })
        if (url === `${prefix}/catalog`)
          return reply({
            bases: [
              {
                id: "kb",
                code: "kb",
                display_name: "合成入库知识库",
                state: "storage_only",
                source_ids: ["source"],
              },
            ],
            indexes: [
              {
                id: "index",
                code: "synthetic-index",
                knowledge_base_id: "kb",
                state: "READY",
                profile_hash: hash,
                corpus_hash: hash,
              },
              {
                id: "index2",
                code: "synthetic-index2",
                knowledge_base_id: "kb",
                state: "READY",
                profile_hash: hash,
                corpus_hash: hash,
              },
              {
                id: "building",
                code: "尚未构建完成",
                knowledge_base_id: "kb",
                state: "BUILDING",
                profile_hash: hash,
                corpus_hash: hash,
              },
              {
                id: "other",
                code: "其他知识库索引",
                knowledge_base_id: "other",
                state: "READY",
                profile_hash: hash,
                corpus_hash: hash,
              },
            ],
          })
        if (url === `${prefix}/resources`)
          return reply({ resources: state.resources })
      }
      calls.push({ url, method, body })
      if (fail)
        return reply(
          {
            detail: {
              error_code: fail,
              message: "synthetic-private-do-not-render",
            },
          },
          fail === "forbidden" ? 403 : 400
        )
      if (url === `${prefix}/content-catalog`)
        return reply({
          bases: [
            {
              id: "kb",
              code: "kb",
              display_name: "合成独立内容库",
              state: "storage_only",
              source_ids: ["remote-source"],
            },
          ],
          indexes: [
            {
              id: "remote-index",
              code: "remote-ready",
              knowledge_base_id: "kb",
              state: "READY",
              profile_hash: hash,
              corpus_hash: hash,
            },
          ],
        })
      if (url === `${prefix}/resources`) {
        const created = { ...resource(), ...body }
        state.resources = [created]
        return reply(created)
      }
      if (url.startsWith(`${prefix}/resources/res/`)) {
        const r = state.resources[0]
        const action = url.split("/").at(-1)
        if (action === "draft") {
          r.draft = {
            id: "draft",
            revision: 1,
            binding_id: null,
            index_id: body.index_id,
            config_hash: hash,
            storage: body.storage ?? null,
          }
          r.verification = null
        }
        if (action === "verify")
          r.verification = { status: "VERIFIED", config_hash: hash }
        if (action === "publish") {
          r.published = r.draft
          r.draft = null
          r.verification = null
        }
        if (action === "status") r.status = body.status
        r.revision = Number(r.revision) + 1
        return reply(r)
      }
      throw new Error("unexpected synthetic request")
    }
  )
  vi.stubGlobal("fetch", fetchMock)
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    calls,
    state,
    fetchMock,
    render: (tabs = false) =>
      render(
        <QueryClientProvider client={client}>
          {tabs ? <ToolResourcesPage /> : <KnowledgeResourcesPage />}
        </QueryClientProvider>
      ),
  }
}
async function openResource() {
  fireEvent.click(
    await screen.findByRole("button", { name: "查看 合成缺陷库" })
  )
  return await screen.findByRole("dialog", { name: "知识资源详情与草稿" })
}

describe("知识资源管理", () => {
  async function selectExternalStorage() {
    fireEvent.change(screen.getByLabelText("连接配置方式"), {
      target: { value: "custom" },
    })
    fireEvent.change(screen.getByLabelText("内容 PostgreSQL"), {
      target: { value: "external" },
    })
    for (const [label, value] of [
      ["PostgreSQL 主机", "synthetic-content"],
      ["内容数据库名", "synthetic_db"],
      ["内容数据库用户名", "synthetic_admin"],
      ["Qdrant 地址", "https://synthetic-qdrant:6333"],
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    await within(screen.getByLabelText("PostgreSQL 密码凭据")).findByRole(
      "option",
      { name: "content-reader" }
    )
    fireEvent.change(screen.getByLabelText("PostgreSQL 密码凭据"), {
      target: { value: "secret://platform/content-reader" },
    })
    expect(document.querySelector('input[type="password"]')).toBeNull()
    expect(screen.queryByLabelText("内容只读用户名")).not.toBeInTheDocument()
    expect(
      screen.getByText(
        "支持管理员、读写或只读账号；当前目录读取和检索仍使用只读事务，不修改知识内容。"
      )
    ).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole("button", { name: "读取内容库与索引目录" })
    )
    await screen.findByText("内容目录已读取；保存后仍需验证并发布。")
  }

  it("独立内容库从所选连接读取目录，创建只提交凭据引用，不发布或授权", async () => {
    const f = setup({ populated: false })
    f.render()
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "新建知识资源" })).toBeEnabled()
    )
    fireEvent.click(screen.getByRole("button", { name: "新建知识资源" }))
    await selectExternalStorage()
    fireEvent.change(screen.getByLabelText("已有知识库"), {
      target: { value: "kb" },
    })
    fireEvent.change(screen.getByLabelText("已有 READY 索引"), {
      target: { value: "remote-index" },
    })
    fireEvent.change(screen.getByLabelText("资源编码"), {
      target: { value: "external-kb" },
    })
    fireEvent.change(screen.getByLabelText("管理名称"), {
      target: { value: "合成独立库" },
    })
    expect(screen.getByRole("button", { name: "创建资源身份" })).toBeEnabled()
    fireEvent.change(screen.getByLabelText("PostgreSQL 主机"), {
      target: { value: "changed-content" },
    })
    expect(screen.getByRole("button", { name: "创建资源身份" })).toBeDisabled()
    expect(
      screen.queryByText("内容目录已读取；保存后仍需验证并发布。")
    ).not.toBeInTheDocument()
    fireEvent.click(
      screen.getByRole("button", { name: "读取内容库与索引目录" })
    )
    await screen.findByText("内容目录已读取；保存后仍需验证并发布。")
    fireEvent.change(screen.getByLabelText("已有知识库"), {
      target: { value: "kb" },
    })
    fireEvent.change(screen.getByLabelText("已有 READY 索引"), {
      target: { value: "remote-index" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建资源身份" }))
    await waitFor(() =>
      expect(f.calls.some((c) => c.url === `${prefix}/resources`)).toBe(true)
    )
    const created = f.calls.find((c) => c.url === `${prefix}/resources`)!.body
    expect(created).toMatchObject({
      knowledge_base_id: "kb",
      index_id: "remote-index",
      storage: {
        postgres: {
          mode: "external",
          host: "changed-content",
          username: "synthetic_admin",
          password_ref: "secret://platform/content-reader",
        },
        qdrant: { url: "https://synthetic-qdrant:6333", api_key_ref: "" },
      },
    })
    expect(
      f.calls.some((c) => /publish|verify|authorization/.test(c.url))
    ).toBe(false)
  })

  it("修改连接使目录失效；保存新草稿使旧验证失效但不替换已发布版本", async () => {
    const f = setup()
    const published = {
      id: "published",
      revision: 1,
      binding_id: null,
      index_id: "index",
      config_hash: hash,
    }
    Object.assign(f.state.resources[0], {
      published,
      draft: { ...published, id: "draft", revision: 2 },
      verification: { status: "VERIFIED", config_hash: hash },
    })
    f.render()
    await openResource()
    await selectExternalStorage()
    fireEvent.change(screen.getByLabelText("已就绪向量索引"), {
      target: { value: "remote-index" },
    })
    expect(screen.getByRole("button", { name: "保存新草稿" })).toBeEnabled()
    fireEvent.change(screen.getByLabelText("Qdrant 地址"), {
      target: { value: "https://changed-qdrant:6333" },
    })
    expect(screen.getByRole("button", { name: "保存新草稿" })).toBeDisabled()
    fireEvent.click(
      screen.getByRole("button", { name: "读取内容库与索引目录" })
    )
    await screen.findByText("内容目录已读取；保存后仍需验证并发布。")
    fireEvent.click(screen.getByRole("button", { name: "保存新草稿" }))
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "发布知识资源" })
      ).toBeDisabled()
    )
    expect(f.state.resources[0].published).toEqual(published)
    expect(f.calls.find((c) => c.url.endsWith("/draft"))?.body).toMatchObject({
      storage: { qdrant: { url: "https://changed-qdrant:6333" } },
    })
  })

  it("从工具资源进入，未选知识库标签时不加载知识 API", async () => {
    const f = setup()
    f.render(true)
    expect(
      f.fetchMock.mock.calls.some(([url]) => String(url).startsWith(prefix))
    ).toBe(false)
    fireEvent.click(screen.getByRole("tab", { name: "知识库" }))
    expect(await screen.findByText("合成缺陷库")).toBeInTheDocument()
    expect(screen.getByText("仅存储")).toBeInTheDocument()
    expect(screen.getByText("未发布")).toBeInTheDocument()
    expect(screen.queryByLabelText("数据库密码")).not.toBeInTheDocument()
  })
  it("显式创建身份、选择草稿、验证、确认发布，并传递最新修订", async () => {
    const f = setup({ populated: false })
    f.render()
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "新建知识资源" })).toBeEnabled()
    )
    fireEvent.click(await screen.findByRole("button", { name: "新建知识资源" }))
    fireEvent.change(screen.getByLabelText("已有知识库"), {
      target: { value: "kb" },
    })
    fireEvent.change(screen.getByLabelText("资源编码"), {
      target: { value: "ones-bugs" },
    })
    fireEvent.change(screen.getByLabelText("管理名称"), {
      target: { value: "合成缺陷库" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建资源身份" }))
    expect(
      await screen.findByRole("group", { name: "数据来源（只读）" })
    ).toHaveTextContent("合成离线批次")
    expect(
      screen.queryByRole("option", { name: /尚未构建完成|其他知识库索引/ })
    ).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("已就绪向量索引"), {
      target: { value: "index" },
    })
    expect(screen.getByRole("button", { name: "发布知识资源" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "保存新草稿" }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "验证草稿" })).toBeEnabled()
    )
    fireEvent.click(screen.getByRole("button", { name: "验证草稿" }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "发布知识资源" })).toBeEnabled()
    )
    fireEvent.click(screen.getByRole("button", { name: "发布知识资源" }))
    expect(f.calls.some((c) => c.url.endsWith("/publish"))).toBe(false)
    fireEvent.click(screen.getByRole("button", { name: "确认操作" }))
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    )
    expect(f.calls.map((c) => [c.method, c.url, c.body])).toEqual([
      [
        "POST",
        `${prefix}/resources`,
        { knowledge_base_id: "kb", code: "ones-bugs", name: "合成缺陷库" },
      ],
      [
        "PUT",
        `${prefix}/resources/res/draft`,
        { expected_revision: 1, index_id: "index" },
      ],
      ["POST", `${prefix}/resources/res/verify`, { expected_revision: 2 }],
      ["POST", `${prefix}/resources/res/publish`, { expected_revision: 3 }],
    ])
  })
  it("并发冲突不覆盖本地选择，也不自动使用新修订重试", async () => {
    const f = setup({ fail: "knowledge_revision_conflict" })
    f.render()
    await openResource()
    fireEvent.change(screen.getByLabelText("已就绪向量索引"), {
      target: { value: "index2" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存新草稿" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("本地输入已保留")
    expect(screen.getByLabelText("已就绪向量索引")).toHaveValue("index2")
    expect(f.calls).toHaveLength(1)
    expect(document.body).not.toHaveTextContent("synthetic-private")
    f.state.resources[0].revision = 9
    fireEvent.click(
      screen.getByRole("button", { name: "重新载入最新配置（替换本地输入）" })
    )
    await waitFor(() =>
      expect(screen.getByLabelText("已就绪向量索引")).toHaveValue("")
    )
  })
  it("技术验证失败只提示本地依赖，不要求 ONES 来源确认", async () => {
    const f = setup({ fail: "knowledge_verification_failed" })
    f.state.resources[0].draft = {
      id: "draft",
      revision: 1,
      binding_id: null,
      index_id: "index",
      config_hash: hash,
    }
    f.state.bindings = []
    f.render()
    await openResource()
    fireEvent.click(screen.getByRole("button", { name: "验证草稿" }))
    const error = await screen.findByRole("alert")
    expect(error).toHaveTextContent("Embedding/Qdrant")
    expect(error).not.toHaveTextContent("本人 ONES 权限")
    expect(document.body).not.toHaveTextContent("synthetic-private")
    expect(screen.getByRole("button", { name: "发布知识资源" })).toBeDisabled()
  })
  it("停用需确认；归档资源只读，不可恢复", async () => {
    const f = setup()
    f.render()
    await openResource()
    fireEvent.click(screen.getByRole("button", { name: "停用资源" }))
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    expect(f.calls).toHaveLength(0)
    fireEvent.click(screen.getByRole("button", { name: "归档资源" }))
    fireEvent.click(screen.getByRole("button", { name: "确认操作" }))
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    )
    expect(
      screen.queryByRole("button", { name: "保存新草稿" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "恢复资源" })
    ).not.toBeInTheDocument()
  })
  it("只读管理权限可看状态但不显示任何写操作", async () => {
    const f = setup({ manage: false })
    f.render()
    const dialog = await openResource()
    expect(
      screen.queryByRole("button", { name: "新建知识资源" })
    ).not.toBeInTheDocument()
    expect(
      within(dialog).getByRole("group", { name: "数据来源（只读）" })
    ).toHaveTextContent("合成离线批次")
    expect(
      screen.queryByRole("button", { name: "发布知识资源" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "建立来源绑定" })
    ).not.toBeInTheDocument()
    expect(f.calls).toHaveLength(0)
  })
  it.each([403, 503])(
    "权限接口 %s 时不读取资源，系统故障不说成无权",
    async (status) => {
      const f = setup({ capsStatus: status })
      f.render()
      expect(await screen.findByRole("alert")).toHaveTextContent(
        status === 403 ? "权限" : "暂不可用"
      )
      expect(
        f.fetchMock.mock.calls.some(([url]) => String(url).startsWith(prefix))
      ).toBe(false)
    }
  )
  it("页面删除来源手工表单，不提供摘要、Job 或来源写操作", async () => {
    const f = setup()
    f.render()
    await screen.findByText("合成缺陷库")
    expect(screen.queryByText("来源确认与核验")).not.toBeInTheDocument()
    expect(
      screen.queryByLabelText(/SHA-256|RUNNING Job/)
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /建立来源绑定|核验来源|撤销核验/ })
    ).not.toBeInTheDocument()
    expect(f.calls).toHaveLength(0)
  })
  it("后端撤销管理权限时写入拒绝，不能由可见按钮绕过", async () => {
    const f = setup({ fail: "forbidden" })
    f.render()
    await openResource()
    fireEvent.click(screen.getByRole("button", { name: "停用资源" }))
    fireEvent.click(screen.getByRole("button", { name: "确认操作" }))
    await waitFor(() =>
      expect(screen.getAllByRole("alert")[0]).toHaveTextContent(
        "没有此知识管理操作权限"
      )
    )
    expect(f.state.resources[0].status).toBe("enabled")
    expect(document.body).not.toHaveTextContent("synthetic-private")
  })
  it("没有来源绑定仍可保存草稿，不要求 ONES 地址或 Team", async () => {
    const f = setup()
    f.state.bindings = []
    f.render()
    await openResource()
    expect(
      screen.getByRole("group", { name: "数据来源（只读）" })
    ).toHaveTextContent("无需确认 ONES 地址或 Team")
    fireEvent.change(screen.getByLabelText("已就绪向量索引"), {
      target: { value: "index" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存新草稿" }))
    await waitFor(() => expect(f.calls).toHaveLength(1))
    expect(f.calls[0].body).toEqual({ expected_revision: 1, index_id: "index" })
    expect(f.calls[0].url).toBe(`${prefix}/resources/res/draft`)
  })
  it.each(["PENDING", "REVOKED", "OTHER_SOURCE", "AMBIGUOUS"])(
    "历史来源 %s 不影响新草稿，也不自动确认来源",
    async (kind) => {
      const f = setup()
      if (kind === "OTHER_SOURCE") f.state.bindings[0].source_id = "other"
      else if (kind === "AMBIGUOUS")
        f.state.bindings.push({ ...f.state.bindings[0], id: "binding2" })
      else f.state.bindings[0].state = kind
      f.render()
      await openResource()
      fireEvent.change(screen.getByLabelText("已就绪向量索引"), {
        target: { value: "index" },
      })
      expect(screen.getByRole("button", { name: "保存新草稿" })).toBeEnabled()
      fireEvent.click(screen.getByRole("button", { name: "保存新草稿" }))
      await waitFor(() => expect(f.calls).toHaveLength(1))
      expect(f.calls[0].body).toEqual({
        expected_revision: 1,
        index_id: "index",
      })
    }
  )
  it("刷新失败仍保留编辑器输入，不把缓存状态误当空资源", async () => {
    const f = setup()
    f.render()
    await openResource()
    fireEvent.change(screen.getByLabelText("已就绪向量索引"), {
      target: { value: "index2" },
    })
    f.fetchMock.mockRejectedValue(new Error("synthetic-private-network-error"))
    fireEvent.click(
      screen.getByRole("button", { name: "重新载入最新配置（替换本地输入）" })
    )
    await waitFor(() =>
      expect(
        screen.getAllByRole("alert", { hidden: true })[0]
      ).toHaveTextContent("暂不可用")
    )
    expect(screen.getByLabelText("已就绪向量索引")).toHaveValue("index2")
    expect(document.body).not.toHaveTextContent("synthetic-private")
    expect(f.calls).toHaveLength(0)
  })
  it("旧来源绑定草稿必须重新保存，不复用旧验证", async () => {
    const f = setup()
    f.state.resources[0].draft = {
      id: "draft",
      revision: 1,
      binding_id: "binding",
      index_id: "index",
      config_hash: hash,
    }
    f.state.resources[0].verification = {
      status: "VERIFIED",
      config_hash: hash,
    }
    f.render()
    await openResource()
    expect(screen.getByText(/此版本使用旧来源确认规则/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "验证草稿" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "发布知识资源" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "保存新草稿" }))
    await waitFor(() => expect(f.calls).toHaveLength(1))
    expect(f.calls[0].body).toEqual({ expected_revision: 1, index_id: "index" })
    expect(screen.getByRole("button", { name: "验证草稿" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "发布知识资源" })).toBeDisabled()
  })
})
