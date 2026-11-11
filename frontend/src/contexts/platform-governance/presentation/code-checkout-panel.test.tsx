import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CodeCheckoutPanel, DirectoryChoices } from "./code-checkout-panel"
import { CodeBrowseDirectory } from "./code-browse-directory"

const url = "https://localhost:18443/repos/mes/trunk"
afterEach(() => vi.unstubAllGlobals())

describe("SVN 工程检出", () => {
  it.each([
    ["CODE_SVN_PROPGET_TIMEOUT", "SVN 外部引用检查超时"],
    ["CODE_SVN_UPDATE_TIMEOUT", "SVN 文件下载或版本更新超时"],
    ["CODE_SVN_EXECUTABLE_NOT_FOUND", "检出服务容器中找不到 SVN 命令"],
    ["CODE_SVN_LOCAL_IO_FAILED", "SVN 执行期间发生本地读写错误"],
    ["code_svn_unavailable", "旧错误记录无法区分超时与容器执行异常"],
    ["code_svn_request_failed", "SVN 命令执行失败"],
    ["CODE_SVN_WC_CLEANUP_REQUIRED", "SVN 工作副本上一次操作尚未完成"],
    ["CODE_SVN_WC_LOCKED", "SVN 工作副本被锁定"],
    ["CODE_SVN_WC_DB_FAILED", "SVN 工作副本元数据数据库异常"],
  ])("检出失败 %s 显示可区分的中文原因", async (code, message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              enabled: true,
              registrations: [],
              checkouts: [],
              jobs: [
                {
                  id: "failed-checkout",
                  operation_kind: "checkout",
                  state: "failed",
                  error_code: code,
                  result: {},
                },
              ],
            }),
            { headers: { "Content-Type": "application/json" } }
          )
      )
    )
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CodeCheckoutPanel resourceId="code-library" />
      </QueryClientProvider>
    )
    expect(await screen.findByText(new RegExp(message))).toBeInTheDocument()
    expect(screen.queryByText(`检出未完成：${code}`)).toBeNull()
  })

  it.each([
    [1, ["E000022", "E200030"], "E000022、E200030"],
    [-9, [], "未提供"],
  ])(
    "检出失败保留安全执行详情（退出码 %s）",
    async (exitCode, codes, expected) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(
          async () =>
            new Response(
              JSON.stringify({
                enabled: true,
                registrations: [],
                checkouts: [],
                jobs: [
                  {
                    id: "diagnostic-checkout",
                    operation_kind: "checkout",
                    state: "failed",
                    error_code: "code_svn_request_failed",
                    result: {
                      diagnostic: {
                        operation: "update",
                        exit_code: exitCode,
                        svn_error_codes: codes,
                        stderr: "synthetic private text must not be rendered",
                      },
                    },
                  },
                ],
              }),
              { headers: { "Content-Type": "application/json" } }
            )
        )
      )
      render(
        <QueryClientProvider
          client={
            new QueryClient({
              defaultOptions: { queries: { retry: false } },
            })
          }
        >
          <CodeCheckoutPanel resourceId="code-library" />
        </QueryClientProvider>
      )
      expect(
        await screen.findByText(/任务 ID：diagnostic-checkout/)
      ).toBeInTheDocument()
      const diagnostic = screen.getByText(
        /失败步骤：下载文件或更新版本（update）/
      )
      expect(diagnostic).toHaveTextContent(`SVN 错误号：${expected}`)
      expect(diagnostic).toHaveTextContent(`退出码：${exitCode}`)
      expect(screen.queryByText(/synthetic private/)).toBeNull()
    }
  )

  it("子目录超限显示中文提示，局部重试保留选择且不传新版本或凭据", async () => {
    const requests: Record<string, unknown>[] = []
    const change = vi.fn()
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input, init) => {
        let data: unknown
        if (init?.method === "POST") {
          requests.push(JSON.parse(String(init.body)))
          data = { id: `child-${requests.length}` }
        } else {
          const failed = String(input).endsWith("child-1")
          data = {
            id: failed ? "child-1" : "child-2",
            operation_kind: "browse",
            state: failed ? "failed" : "succeeded",
            error_code: failed ? "code_svn_response_too_large" : null,
            result: failed
              ? {}
              : {
                  revision: 2,
                  directory_path: "module",
                  directories: [],
                  files: ["module/rule.cpp"],
                },
          }
        }
        return new Response(JSON.stringify(data), {
          headers: { "Content-Type": "application/json" },
        })
      })
    )
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CodeBrowseDirectory
          resourceId="code-library"
          browseId="root-r2"
          path="module"
          revision={2}
          selected={["README.md"]}
          onChange={change}
        />
      </QueryClientProvider>
    )
    expect(
      await screen.findByText(/SVN 返回的数据超过单次处理上限/)
    ).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText("重试加载 module"))
    fireEvent.click(await screen.findByLabelText("选择 module/rule.cpp"))
    expect(change).toHaveBeenCalledWith(["README.md", "module/rule.cpp"])
    expect(requests).toHaveLength(2)
    expect(requests[0]).toEqual({
      browse_job_id: "root-r2",
      path: "module",
      request_key: expect.any(String),
    })
    expect(requests[1].request_key).not.toEqual(requests[0].request_key)
  })

  it("无需认证按输入地址直连，不使用同 URL 的部署映射或账号", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input, init) => {
        const path = String(input)
        let data: unknown = {
          enabled: true,
          registrations: [
            { id: "mes-local", url, kind: "deployment" },
            { id: "saved-account", url, kind: "account" },
          ],
          jobs: [],
          checkouts: [],
        }
        if (init?.method === "POST") {
          const body = JSON.parse(String(init.body))
          requests.push({ path, body })
          data = {
            id: path.endsWith("/connections")
              ? "direct-anonymous"
              : "direct-browse",
          }
        } else if (path.endsWith("/direct-browse")) {
          data = {
            id: "direct-browse",
            operation_kind: "browse",
            state: "succeeded",
            error_code: null,
            result: {
              revision: 2,
              directories: ["set_server"],
              files: ["README.md"],
            },
          }
        }
        return new Response(JSON.stringify(data), {
          headers: { "Content-Type": "application/json" },
        })
      })
    )
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CodeCheckoutPanel resourceId="code-library" />
      </QueryClientProvider>
    )
    await waitFor(() =>
      expect(screen.getByLabelText("SVN 仓库地址")).toHaveValue(url)
    )
    expect(screen.queryByLabelText("已保存 SVN 连接")).toBeNull()
    expect(screen.queryByLabelText("SVN 用户名")).toBeNull()
    expect(screen.getByLabelText("SVN 认证方式")).toHaveValue("anonymous")
    expect(screen.getByRole("option", { name: "无需认证" })).toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent("不自动替换地址")
    fireEvent.click(screen.getByRole("button", { name: "浏览目录" }))
    await screen.findByText(/已固定 SVN r2/)
    expect(requests[0].path).toMatch(/\/connections$/)
    expect(requests[0].body).toEqual({ url, authentication: "anonymous" })
    expect(requests[1].body).toMatchObject({
      url,
      connection_id: "direct-anonymous",
    })
    fireEvent.click(screen.getByRole("button", { name: "浏览目录" }))
    await waitFor(() => expect(requests).toHaveLength(3))
    expect(requests[2].body.connection_id).toBe("direct-anonymous")
    expect(
      requests.filter((item) => item.path.endsWith("/connections"))
    ).toHaveLength(1)
  })

  it("保存账号密码后只用连接标识浏览，页面不保留密码", async () => {
    const requests: { path: string; body: Record<string, unknown> }[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input, init) => {
        const path = String(input)
        let data: unknown = {
          enabled: true,
          registrations: [],
          jobs: [],
          checkouts: [],
        }
        if (init?.method === "POST") {
          requests.push({ path, body: JSON.parse(String(init.body)) })
          data = {
            id: path.endsWith("/connections")
              ? "saved-connection"
              : "pending-browse",
          }
        } else if (path.endsWith("/pending-browse")) {
          data = {
            id: "pending-browse",
            operation_kind: "browse",
            state: "failed",
            error_code: "CODE_SVN_AUTH_FAILED",
            result: {},
          }
        }
        return new Response(JSON.stringify(data), {
          headers: { "Content-Type": "application/json" },
        })
      })
    )
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CodeCheckoutPanel resourceId="code-library" />
      </QueryClientProvider>
    )
    fireEvent.change(await screen.findByLabelText("SVN 仓库地址"), {
      target: { value: "https://svn.invalid/project/trunk" },
    })
    expect(screen.getByLabelText("SVN 认证方式")).toHaveValue("anonymous")
    fireEvent.change(screen.getByLabelText("SVN 认证方式"), {
      target: { value: "account" },
    })
    fireEvent.change(screen.getByLabelText("SVN 用户名"), {
      target: { value: "synthetic-user" },
    })
    fireEvent.change(screen.getByLabelText("SVN 密码"), {
      target: { value: "synthetic-password" },
    })
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "保存连接并浏览" })
      ).toBeEnabled()
    )
    fireEvent.click(screen.getByRole("button", { name: "保存连接并浏览" }))
    await waitFor(() => expect(requests).toHaveLength(2))
    expect(requests[0].body).toEqual({
      url: "https://svn.invalid/project/trunk",
      authentication: "account",
      username: "synthetic-user",
      password: "synthetic-password",
    })
    expect(requests[1].body).toMatchObject({
      connection_id: "saved-connection",
    })
    expect(JSON.stringify(requests[1])).not.toContain("synthetic-password")
    expect(
      await screen.findByText(/SVN 用户名或密码不正确/)
    ).toBeInTheDocument()
    expect(screen.getByLabelText("SVN 认证方式")).toHaveValue("account")
    expect(screen.getByLabelText("SVN 密码")).toHaveValue("")
    expect(screen.getByText(/账号凭据已保存/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "浏览目录" }))
    await waitFor(() => expect(requests).toHaveLength(3))
    expect(
      requests.filter((item) => item.path.endsWith("/connections"))
    ).toHaveLength(1)
    expect(requests[2].body.connection_id).toBe("saved-connection")
    fireEvent.change(screen.getByLabelText("SVN 用户名"), {
      target: { value: "changed-user" },
    })
    expect(
      screen.getByRole("button", { name: "保存连接并浏览" })
    ).toBeDisabled()
    fireEvent.change(screen.getByLabelText("SVN 密码"), {
      target: { value: "replacement-synthetic" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存连接并浏览" }))
    await waitFor(() => expect(requests).toHaveLength(5))
    expect(requests[3].body.username).toBe("changed-user")
    expect(screen.getByLabelText("SVN 认证方式")).toHaveValue("account")
    fireEvent.change(screen.getByLabelText("SVN 仓库地址"), {
      target: { value: "https://svn.invalid/another/trunk" },
    })
    expect(screen.getByLabelText("SVN 认证方式")).toHaveValue("account")
    expect(
      screen.getByRole("button", { name: "保存连接并浏览" })
    ).toBeDisabled()
    fireEvent.change(screen.getByLabelText("SVN 认证方式"), {
      target: { value: "anonymous" },
    })
    fireEvent.click(screen.getByRole("button", { name: "浏览目录" }))
    await waitFor(() => expect(requests).toHaveLength(7))
    expect(requests[5].body).toEqual({
      url: "https://svn.invalid/another/trunk",
      authentication: "anonymous",
    })
    expect(screen.getByLabelText("SVN 认证方式")).toHaveValue("anonymous")
  })
  it("展开目录并多选，父目录选择会移除重复子目录", () => {
    const change = vi.fn()
    render(
      <DirectoryChoices
        directories={["set_web", "set_web/EBR", "set_web/JTH"]}
        files={["README.md", "set_web/EBR/package.json", "set_web/EBR/.env"]}
        selected={["set_web/EBR"]}
        onChange={change}
      />
    )
    fireEvent.click(screen.getByRole("button", { name: "展开 set_web" }))
    expect(screen.getByText("README.md")).toBeInTheDocument()
    expect(screen.queryByText("package.json")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "展开 set_web/EBR" }))
    expect(screen.getByText("package.json")).toBeInTheDocument()
    expect(screen.getByText(".env")).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: /package.json/ })).toBeChecked()
    expect(
      screen.getByRole("checkbox", { name: /package.json/ })
    ).toBeDisabled()
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 README.md" }))
    expect(change).toHaveBeenLastCalledWith(["set_web/EBR", "README.md"])
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 set_web/JTH" }))
    expect(change).toHaveBeenLastCalledWith(["set_web/EBR", "set_web/JTH"])
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 set_web" }))
    expect(change).toHaveBeenLastCalledWith(["set_web"])
  })

  it("浏览固定版本后提交所选目录，不发送宿主机路径或模型请求", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        const path = String(input)
        if (init?.method === "POST") {
          requests.push({ path, body: JSON.parse(String(init.body)) })
          return new Response(
            JSON.stringify({
              id: path.endsWith("/connections")
                ? "direct-anonymous"
                : path.endsWith("/browse-children")
                  ? "child-id"
                  : path.endsWith("/browse")
                    ? "browse-id"
                    : "checkout-id",
            }),
            { status: 202, headers: { "Content-Type": "application/json" } }
          )
        }
        const data = path.endsWith("/child-id")
          ? {
              id: "child-id",
              operation_kind: "browse",
              state: "succeeded",
              error_code: null,
              result: {
                revision: 2,
                directory_path: "set_web",
                directories: ["set_web/EBR", "set_web/JTH"],
                files: ["set_web/README.md"],
              },
            }
          : path.endsWith("/browse-id")
            ? {
                id: "browse-id",
                operation_kind: "browse",
                state: "succeeded",
                error_code: null,
                result: {
                  revision: 2,
                  files: ["README.md"],
                  directories: ["set_server", "set_web"],
                },
              }
            : {
                enabled: true,
                registrations: [{ id: "test-svn", url, kind: "deployment" }],
                jobs: [],
                checkouts: [],
              }
        return new Response(JSON.stringify(data), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      })
    )
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CodeCheckoutPanel resourceId="code-library" />
      </QueryClientProvider>
    )
    await waitFor(() =>
      expect(screen.getByLabelText("SVN 仓库地址")).toHaveValue(url)
    )
    fireEvent.click(screen.getByRole("button", { name: "浏览目录" }))
    await screen.findByText(/已固定 SVN r2/)
    expect(requests).toHaveLength(2)
    expect(screen.queryByLabelText("选择 set_web/EBR")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "展开 set_web" }))
    await screen.findByLabelText("选择 set_web/EBR")
    expect(requests[2].body).toMatchObject({
      browse_job_id: "browse-id",
      path: "set_web",
    })
    expect(requests[2].body).not.toHaveProperty("revision")
    fireEvent.click(screen.getByRole("button", { name: "展开 set_web" }))
    fireEvent.click(screen.getByRole("button", { name: "展开 set_web" }))
    expect(requests).toHaveLength(3)
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 set_web/EBR" }))
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 set_web/JTH" }))
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 README.md" }))
    fireEvent.change(screen.getByLabelText("目标子目录"), {
      target: { value: "factory-r2" },
    })
    fireEvent.click(screen.getByRole("button", { name: "检出所选内容" }))
    await waitFor(() => expect(requests).toHaveLength(4))
    expect(requests[3].body).toMatchObject({
      browse_job_id: "browse-id",
      paths: ["set_web/EBR", "set_web/JTH", "README.md"],
      folder: "factory-r2",
    })
    expect(
      requests.every((request) =>
        request.path.startsWith(
          "/api/platform/knowledge/code/resources/code-library/"
        )
      )
    ).toBe(true)
    fireEvent.change(screen.getByLabelText("SVN 仓库地址"), {
      target: { value: "https://other.test/" },
    })
    expect(screen.queryByRole("button", { name: "检出所选内容" })).toBeNull()
  })
})
