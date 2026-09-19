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
            binding_id: body.binding_id,
            index_id: body.index_id,
            config_hash: hash,
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
      if (url === `${prefix}/source-bindings`) {
        const binding = {
          id: "binding2",
          ...body,
          revision: Number(body.expected_revision) + 1,
          state: "PENDING",
        }
        state.bindings = [{ ...state.bindings[0], state: "REVOKED" }, binding]
        return reply(binding)
      }
      if (url.endsWith("/verify"))
        return reply({ ...state.bindings[0], state: "VERIFIED" })
      if (url.endsWith("/revoke")) {
        state.bindings[0].state = "REVOKED"
        return reply({ revoked: true })
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
    const binding = await screen.findByLabelText("已核验来源绑定")
    expect(binding).toHaveValue("")
    expect(
      screen.queryByRole("option", { name: /尚未构建完成|其他知识库索引/ })
    ).not.toBeInTheDocument()
    fireEvent.change(binding, { target: { value: "binding" } })
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
        { expected_revision: 1, binding_id: "binding", index_id: "index" },
      ],
      ["POST", `${prefix}/resources/res/verify`, { expected_revision: 2 }],
      ["POST", `${prefix}/resources/res/publish`, { expected_revision: 3 }],
    ])
  })
  it("并发冲突不覆盖本地选择，也不自动使用新修订重试", async () => {
    const f = setup({ fail: "knowledge_revision_conflict" })
    f.render()
    await openResource()
    fireEvent.change(screen.getByLabelText("已核验来源绑定"), {
      target: { value: "binding" },
    })
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
    expect(within(dialog).getByLabelText("已核验来源绑定")).toBeDisabled()
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
  it("来源需要明确证明及确认，不自动技术核验", async () => {
    const f = setup()
    f.render()
    await screen.findByText("合成缺陷库")
    fireEvent.click(screen.getByText("来源确认与核验"))
    fireEvent.change(screen.getByLabelText("离线来源"), {
      target: { value: "source" },
    })
    fireEvent.change(screen.getByLabelText("受信 ONES 实例编码"), {
      target: { value: "default" },
    })
    fireEvent.change(screen.getByLabelText("ONES 原生 Team ID"), {
      target: { value: "team" },
    })
    fireEvent.change(screen.getByLabelText("批次来源证明 SHA-256 摘要"), {
      target: { value: hash },
    })
    expect(screen.getByRole("button", { name: "建立来源绑定" })).toBeDisabled()
    fireEvent.click(
      screen.getByLabelText("我已确认完整批次来源，证明原件保留在受限位置")
    )
    fireEvent.click(screen.getByRole("button", { name: "建立来源绑定" }))
    expect(f.calls).toHaveLength(0)
    fireEvent.click(screen.getByRole("button", { name: "确认操作" }))
    await waitFor(() => expect(f.calls).toHaveLength(1))
    expect(f.calls[0].body).toEqual({
      source_id: "source",
      instance_code: "default",
      team_id: "team",
      expected_revision: 1,
      batch_attested: true,
      attestation_hash: hash,
    })
    expect(f.calls[0].url).toBe(`${prefix}/source-bindings`)
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
  it("来源核验只提交 Job ID；撤销需要确认且不删除数据", async () => {
    const f = setup()
    f.render()
    await screen.findByText("合成缺陷库")
    fireEvent.click(screen.getByText("来源确认与核验"))
    fireEvent.change(screen.getByLabelText("本人 RUNNING Job ID（binding）"), {
      target: { value: "synthetic-job" },
    })
    fireEvent.click(screen.getByRole("button", { name: "核验来源" }))
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "撤销核验" })).toBeEnabled()
    )
    expect(f.calls[0]).toEqual({
      url: `${prefix}/source-bindings/binding/verify`,
      method: "POST",
      body: { job_id: "synthetic-job" },
    })
    fireEvent.click(screen.getByRole("button", { name: "撤销核验" }))
    expect(f.calls).toHaveLength(1)
    fireEvent.click(screen.getByRole("button", { name: "确认操作" }))
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    )
    expect(f.calls[1]).toEqual({
      url: `${prefix}/source-bindings/binding/revoke`,
      method: "POST",
      body: {},
    })
    expect(screen.getByText(/已撤销/)).toBeInTheDocument()
  })
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
})
