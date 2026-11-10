import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CodeCheckoutPanel, DirectoryChoices } from "./code-checkout-panel"

const url = "https://localhost:18443/repos/mes/trunk"
afterEach(() => vi.unstubAllGlobals())

describe("SVN 工程检出", () => {
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
    fireEvent.change(screen.getByLabelText("SVN 认证方式"), {
      target: { value: "account" },
    })
    expect(screen.getByLabelText("SVN 密码")).toHaveValue("")
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
              id: path.endsWith("/browse") ? "browse-id" : "checkout-id",
            }),
            { status: 202, headers: { "Content-Type": "application/json" } }
          )
        }
        const data = path.endsWith("/browse-id")
          ? {
              id: "browse-id",
              operation_kind: "browse",
              state: "succeeded",
              error_code: null,
              result: {
                revision: 2,
                files: ["README.md"],
                directories: [
                  "set_server",
                  "set_web",
                  "set_web/EBR",
                  "set_web/JTH",
                ],
              },
            }
          : {
              enabled: true,
              registrations: [{ id: "test-svn", url }],
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
    fireEvent.click(screen.getByRole("button", { name: "展开 set_web" }))
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 set_web/EBR" }))
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 set_web/JTH" }))
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 README.md" }))
    fireEvent.change(screen.getByLabelText("目标子目录"), {
      target: { value: "factory-r2" },
    })
    fireEvent.click(screen.getByRole("button", { name: "检出所选内容" }))
    await waitFor(() => expect(requests).toHaveLength(2))
    expect(requests[1].body).toMatchObject({
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
