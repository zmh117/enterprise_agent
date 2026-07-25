import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { UserDetailPage } from "@/contexts/users/presentation/user-detail-page"
import { UsersPage } from "@/contexts/users/presentation/users-page"

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  )
}

function user(overrides: Record<string, unknown> = {}) {
  return {
    id: "user-1",
    username: "zmh",
    display_name: "庄慕焕",
    email: "zmh@example.test",
    status: "enabled",
    account_type: "human",
    revision: 3,
    created_at: "2026-07-20T00:00:00+08:00",
    updated_at: "2026-07-23T10:00:00+08:00",
    ...overrides,
  }
}

function identity(overrides: Record<string, unknown> = {}) {
  return {
    id: "identity-1",
    user_id: "user-1",
    provider: "dingtalk",
    tenant_code: "default",
    external_subject_id: "03695725024624053732",
    connector_id: "connector-dingtalk-stream-default",
    union_id: "",
    open_id: "",
    display_name: "庄慕焕",
    status: "enabled",
    verified_at: "2026-07-22T00:00:00+08:00",
    last_seen_at: "2026-07-23T00:00:00+08:00",
    metadata: { verification_method: "trusted_connector" },
    revision: 1,
    created_at: "2026-07-22T00:00:00+08:00",
    updated_at: "2026-07-23T00:00:00+08:00",
    ...overrides,
  }
}

function providers() {
  return {
    providers: [
      { code: "dingtalk", display_name: "钉钉", available: true },
      {
        code: "ones",
        display_name: "ONES",
        available: true,
        instance_code: "default",
      },
    ],
  }
}

function tenants() {
  return {
    tenants: [
      {
        connector_id: "connector-dingtalk-stream-default",
        name: "默认钉钉 Stream",
        tenant_code: "default",
      },
    ],
  }
}

function renderUsers() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function renderDetail() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/users/user-1"]}>
        <Routes>
          <Route path="/users/:userId" element={<UserDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("User and external identity management", () => {
  it("renders real paginated users and searches without fixture fallback", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), "http://admin.test")
      expect(url.searchParams.get("page_size")).toBe("20")
      return response({
        users: [user()],
        pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 },
      })
    })
    renderUsers()
    expect(await screen.findByText("庄慕焕")).toBeInTheDocument()
    expect(screen.getByText("zmh · zmh@example.test")).toBeInTheDocument()
    expect(screen.getByText("人员账号")).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("搜索用户"), {
      target: { value: "036957" },
    })
    fireEvent.click(screen.getByRole("button", { name: "搜索" }))
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    expect(new URL(String(fetch.mock.calls[1][0]), "http://admin.test").searchParams.get("search"))
      .toBe("036957")
  })

  it("creates a user and clears the optional password after submission", async () => {
    let submittedBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "POST") {
        submittedBody = JSON.parse(String(init.body))
        return response({ user: user({ id: "user-new", username: "new-user" }) })
      }
      return response({
        users: [],
        pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
      })
    })
    renderUsers()
    await screen.findByText("没有找到符合条件的用户。")
    fireEvent.click(screen.getByRole("button", { name: "新建用户" }))
    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "new-user" },
    })
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "New User" },
    })
    fireEvent.change(screen.getByLabelText("初始密码（可选）"), {
      target: { value: "new-user-password" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建用户" }))

    await waitFor(() =>
      expect(submittedBody).toMatchObject({
        username: "new-user",
        password: "new-user-password",
      }),
    )
    await waitFor(() =>
      expect(screen.queryByLabelText("初始密码（可选）")).not.toBeInTheDocument(),
    )
  })

  it("shows user detail and binds DingTalk only through a trusted tenant option", async () => {
    let bindingBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/external-identity-providers")) return response(providers())
      if (url.endsWith("/dingtalk-tenants")) return response(tenants())
      if (url.endsWith("/dingtalk-identities") && init?.method === "POST") {
        bindingBody = JSON.parse(String(init.body))
        return response({ identity: identity() })
      }
      if (url.endsWith("/users/user-1")) {
        return response({ user: user(), identities: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail()
    expect(await screen.findByText("基本资料")).toBeInTheDocument()
    expect(await screen.findByText("该用户尚未绑定钉钉或 ONES 身份。"))
      .toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "绑定钉钉" }))
    fireEvent.change(screen.getByLabelText("钉钉租户 / 连接器"), {
      target: { value: "connector-dingtalk-stream-default" },
    })
    fireEvent.change(screen.getByLabelText("senderStaffId"), {
      target: { value: "03695725024624053732" },
    })
    fireEvent.click(screen.getByRole("button", { name: "绑定钉钉" }))
    await waitFor(() =>
      expect(bindingBody).toEqual({
        expected_user_revision: 3,
        tenant_code: "default",
        external_subject_id: "03695725024624053732",
        connector_id: "connector-dingtalk-stream-default",
        display_name: "",
      }),
    )
  })

  it("shows a stable revision conflict instead of overwriting newer user data", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/external-identity-providers")) return response(providers())
      if (url.endsWith("/dingtalk-tenants")) return response(tenants())
      if (url.endsWith("/users/user-1") && init?.method === "PUT") {
        return response(
          {
            detail: {
              code: "revision_conflict",
              message: "用户信息已被修改，请刷新后重试",
            },
          },
          409,
        )
      }
      if (url.endsWith("/users/user-1")) {
        return response({ user: user(), identities: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail()
    fireEvent.change(await screen.findByLabelText("显示名称"), {
      target: { value: "并发覆盖尝试" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存资料" }))
    expect(
      await screen.findByText("用户信息已被修改，请刷新后重试"),
    ).toBeInTheDocument()
  })

  it("submits only ONES email/password and clears password after a failed request", async () => {
    let bindingBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/external-identity-providers")) return response(providers())
      if (url.endsWith("/dingtalk-tenants")) return response(tenants())
      if (url.endsWith("/ones-identities") && init?.method === "POST") {
        bindingBody = JSON.parse(String(init.body))
        return response(
          {
            detail: {
              code: "ones_invalid_credentials",
              message: "ONES 邮箱或密码错误",
            },
          },
          400,
        )
      }
      if (url.endsWith("/users/user-1")) {
        return response({ user: user(), identities: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail()
    await screen.findByText("基本资料")
    fireEvent.click(await screen.findByRole("button", { name: "绑定 ONES" }))
    fireEvent.change(screen.getByLabelText("ONES 邮箱"), {
      target: { value: "zmh@example.test" },
    })
    const password = screen.getByLabelText("一次性验证密码")
    fireEvent.change(password, { target: { value: "ones-password" } })
    fireEvent.click(screen.getByRole("button", { name: "验证并绑定" }))

    expect(
      await screen.findByText("ONES 邮箱或密码错误"),
    ).toBeInTheDocument()
    expect(bindingBody).toEqual({
      expected_user_revision: 3,
      email: "zmh@example.test",
      password: "ones-password",
    })
    expect(password).toHaveValue("")
    for (const forbidden of ["uuid", "token", "url", "metadata", "team"]) {
      expect(bindingBody).not.toHaveProperty(forbidden)
    }
  })

  it("changes identity state, confirms soft unbind, and disables personal binding for service accounts", async () => {
    let currentIdentity = identity()
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/external-identity-providers")) return response(providers())
      if (url.endsWith("/dingtalk-tenants")) return response(tenants())
      if (url.includes("/identities/identity-1/status") && init?.method === "PUT") {
        currentIdentity = identity({ status: "disabled", revision: 2 })
        return response({ identity: currentIdentity })
      }
      if (url.includes("/identities/identity-1?") && init?.method === "DELETE") {
        currentIdentity = identity({ status: "unbound", revision: 3 })
        return response({ identity: currentIdentity })
      }
      if (url.endsWith("/users/user-1")) {
        return response({ user: user(), identities: [currentIdentity] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const firstRender = renderDetail()
    fireEvent.click(await screen.findByRole("button", { name: "停用身份" }))
    await waitFor(() =>
      expect(fetch.mock.calls.some((call) => String(call[0]).includes("/status")))
        .toBe(true),
    )
    fireEvent.click(await screen.findByRole("button", { name: "解绑" }))
    fireEvent.click(screen.getByRole("button", { name: "确认解绑" }))
    await waitFor(() =>
      expect(fetch.mock.calls.some((call) => String(call[0]).includes("?expected_revision=2")))
        .toBe(true),
    )

    firstRender.unmount()
    vi.restoreAllMocks()
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/external-identity-providers")) return response(providers())
      if (url.endsWith("/dingtalk-tenants")) return response(tenants())
      return response({
        user: user({ account_type: "service" }),
        identities: [],
      })
    })
    renderDetail()
    expect(await screen.findByRole("button", { name: "绑定钉钉" }))
      .toBeDisabled()
    expect(screen.getByRole("button", { name: "绑定 ONES" })).toBeDisabled()
    expect(
      screen.getByText("服务账号不能绑定个人外部身份。"),
    ).toBeInTheDocument()
  })
})
