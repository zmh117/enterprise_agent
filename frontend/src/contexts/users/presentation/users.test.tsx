import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { UserDetailPage } from "@/contexts/users/presentation/user-detail-page"
import { UsersPage } from "@/contexts/users/presentation/users-page"
import { MyExternalIdentitiesPage } from "@/contexts/external-identities"
import { AuthenticatedUserProvider } from "@/contexts/auth/presentation/authenticated-user-context"
import type { AuthenticatedUser } from "@/contexts/auth/domain/authenticated-user"

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
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

function authenticatedUser(
  overrides: Partial<AuthenticatedUser> = {}
): AuthenticatedUser {
  return {
    id: "user-admin",
    username: "admin",
    display_name: "平台管理员",
    roles: ["platform-admin"],
    auth_source: "local",
    capabilities: {},
    ...overrides,
  }
}

function adminDingTalkIdentity(overrides: Record<string, unknown> = {}) {
  return {
    provider: "dingtalk",
    identity_id: "identity-1",
    nickname: "庄慕焕",
    status: "enabled",
    enterprise: { name: "默认钉钉企业", corp_id: "corp-default" },
    last_used_at: "2026-07-23T00:00:00+08:00",
    staff_id: "03695725024624053732",
    binding_confirmed_at: "2026-07-22T00:00:00+08:00",
    revision: 1,
    observations: [],
    ...overrides,
  }
}

function adminOnesIdentity(overrides: Record<string, unknown> = {}) {
  return {
    provider: "ones",
    identity_id: "identity-ones",
    status: "enabled",
    revision: 2,
    user_name: "ONES 用户",
    default_team: { id: "team-default", name: "默认 Team" },
    verified_at: "2026-07-22T00:00:00+08:00",
    user_id: "ones-user-1",
    teams: [{ id: "team-default", name: "默认 Team" }],
    credential: {
      configured: true,
      status: "ACTIVE",
      revision: 2,
      verified_at: "2026-07-22T00:00:00+08:00",
      token_refreshed_at: null,
      last_used_at: null,
      reauth_required_at: null,
      disabled_at: null,
      unbound_at: null,
    },
    ...overrides,
  }
}

function adminOverview(
  current: Array<Record<string, unknown>> = [],
  history: Array<Record<string, unknown>> = []
) {
  return { user_id: "user-1", current, history }
}

function selfDingTalkIdentity(overrides: Record<string, unknown> = {}) {
  const identity: Record<string, unknown> = {
    ...adminDingTalkIdentity(overrides),
  }
  delete identity.identity_id
  delete identity.revision
  return identity
}

function selfOnesIdentity(overrides: Record<string, unknown> = {}) {
  const identity: Record<string, unknown> = {
    ...adminOnesIdentity(overrides),
  }
  delete identity.identity_id
  delete identity.revision
  return identity
}

function selfOverview(
  dingtalk: Array<Record<string, unknown>> = [],
  ones: Record<string, unknown> | null = null
) {
  return {
    user: { id: "user-1", display_name: "庄慕焕" },
    dingtalk,
    ones,
  }
}

function emptyRoles() {
  return {
    items: [],
    page: { limit: 100, offset: 0, total: 0 },
  }
}

function assignableRoles() {
  return {
    items: [1, 2].map((index) => ({
      id: `role-${index}`,
      code: `diagnostic-role-${index}`,
      name: `诊断角色 ${index}`,
      description: "",
      status: "enabled",
      origin: "custom",
      protected: false,
      purpose_tags: ["业务诊断"],
      metadata_revision: 1,
      admin_revision: 1,
      business_revision: 1,
      membership_revision: 1,
      member_count: 0,
      admin_capability_count: 0,
      application_count: 1,
    })),
    page: { limit: 100, offset: 0, total: 2 },
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
    </QueryClientProvider>
  )
}

function renderMyExternalIdentities() {
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
      <MemoryRouter>
        <MyExternalIdentitiesPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function discoveryCandidate(overrides: Record<string, unknown> = {}) {
  const message = {
    id: "candidate-message-1",
    connector_id: "connector-dingtalk-stream-default",
    connector_name: "默认钉钉 Stream",
    robot_code: "robot-default",
    conversation_type: "direct",
    conversation_id: "staff-001",
    message_kind: "text",
    safe_text: "请给我开通",
    text_truncated: false,
    attachment_type: "",
    attachment_name: "",
    attachment_size: null,
    occurred_at: "2026-07-26T01:00:00+00:00",
    received_at: "2026-07-26T01:00:01+00:00",
  }
  return {
    id: "candidate-1",
    dingtalk_enterprise_id: "enterprise-default",
    enterprise_name: "默认钉钉企业",
    corp_id: "corp-default",
    external_subject_id: "staff-001",
    display_name: "待绑定张三",
    first_seen_at: "2026-07-26T01:00:01+00:00",
    last_seen_at: "2026-07-26T01:00:01+00:00",
    observation_count: 1,
    revision: 2,
    identity_state: "waiting_bind",
    conversation_scope: "direct",
    group_ids: [],
    robot_codes: ["robot-default"],
    connector_names: ["默认钉钉 Stream"],
    latest_message: message,
    messages: [message],
    historical_identity: null,
    ...overrides,
  }
}

function renderDetail(
  initialEntry = "/users/user-1",
  currentUser = authenticatedUser()
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AuthenticatedUserProvider user={currentUser}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route path="/users/:userId" element={<UserDetailPage />} />
          </Routes>
        </MemoryRouter>
      </AuthenticatedUserProvider>
    </QueryClientProvider>
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
    expect(
      new URL(
        String(fetch.mock.calls[1][0]),
        "http://admin.test"
      ).searchParams.get("search")
    ).toBe("036957")
  })

  it("creates a user and clears the optional password after submission", async () => {
    let submittedBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "POST") {
        submittedBody = JSON.parse(String(init.body))
        return response({
          user: user({ id: "user-new", username: "new-user" }),
        })
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
      })
    )
    await waitFor(() =>
      expect(
        screen.queryByLabelText("初始密码（可选）")
      ).not.toBeInTheDocument()
    )
  })

  it("removes manual DingTalk binding and routes administrators to trusted candidates", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/api/admin/authorization/roles?"))
        return response(emptyRoles())
      if (url.endsWith("/users/user-1/external-identities"))
        return response(adminOverview())
      if (url.endsWith("/users/user-1")) {
        return response({ user: user() })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail()
    expect(await screen.findByText("基本资料")).toBeInTheDocument()
    expect(
      await screen.findByText("该用户当前没有已绑定的钉钉或 ONES 身份。")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "从受信候选绑定钉钉" })
    ).toBeInTheDocument()
    expect(screen.queryByLabelText("senderStaffId")).toBeNull()
    expect(screen.queryByLabelText("钉钉租户 / 连接器")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "从受信候选绑定钉钉" }))
    expect(window.location.pathname).not.toContain("dingtalk-identities")
  })

  it("separates current identities from collapsed read-only history", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/api/admin/authorization/roles?"))
        return response(emptyRoles())
      if (url.endsWith("/users/user-1/external-identities")) {
        return response(
          adminOverview(
            [
              adminDingTalkIdentity({
                identity_id: "identity-current",
                nickname: "Current DingTalk User",
              }),
            ],
            [
              adminOnesIdentity({
                identity_id: "identity-history",
                status: "unbound",
                user_name: "Historical ONES User",
                user_id: "ones-history-user",
                teams: [{ id: "legacy-team", name: "" }],
                default_team: null,
              }),
            ]
          )
        )
      }
      if (url.endsWith("/users/user-1")) {
        return response({ user: user() })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderDetail()

    expect(await screen.findByText("Current DingTalk User")).toBeInTheDocument()
    const history = await screen.findByTestId("external-identity-history")
    expect(history).not.toHaveAttribute("open")
    expect(screen.queryByRole("button", { name: "恢复身份" })).toBeNull()

    fireEvent.click(screen.getByText("历史记录（1）"))
    await waitFor(() => expect(history).toHaveAttribute("open"))
    expect(screen.getByText("Historical ONES User")).toBeVisible()
    expect(screen.getByText("历史 ONES 身份")).toBeVisible()
    expect(screen.queryByRole("button", { name: "软解绑 ONES" })).toBeNull()
  })

  it("shows ONES identity facts and current credential status without legacy connection state", async () => {
    const ones = adminOnesIdentity({
      default_team: { id: "team-id-only", name: "" },
      teams: [{ id: "team-id-only", name: "" }],
      credential: null,
    })
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/api/admin/authorization/roles?")) {
        return response(emptyRoles())
      }
      if (url.endsWith("/users/user-1/external-identities")) {
        return response(adminOverview([ones]))
      }
      if (url.endsWith("/users/user-1")) {
        return response({ user: user() })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderDetail()

    expect(
      (await screen.findAllByText("team-id-only（名称暂不可用）")).length
    ).toBeGreaterThan(0)
    expect(screen.getByText("管理员只能查看、停用和审计；重新验证与解绑必须由用户本人完成。")).toBeInTheDocument()
    expect(screen.getAllByText("需要本人重新验证").length).toBeGreaterThan(0)
    expect(screen.queryByText(/历史连接|Connection/)).toBeNull()
  })

  it("shows administrator-disabled ONES identity without management credential actions", async () => {
    const ones = adminOnesIdentity({ status: "disabled" })
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/api/admin/authorization/roles?")) {
        return response(emptyRoles())
      }
      if (url.endsWith("/users/user-1/external-identities")) {
        return response(adminOverview([ones]))
      }
      if (url.endsWith("/users/user-1")) {
        return response({ user: user() })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderDetail()

    expect((await screen.findAllByText("已停用")).length).toBeGreaterThan(0)
    expect(screen.queryByRole("button", { name: "启用身份" })).toBeNull()
    expect(screen.queryByRole("button", { name: "解绑" })).toBeNull()
    expect(screen.getByText("可用 · r2")).toBeInTheDocument()
    expect(screen.queryByText(/Connection/)).toBeNull()
  })

  it("opens history and offers restore only for a matching trusted candidate", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/api/admin/authorization/roles?"))
        return response(emptyRoles())
      if (url.endsWith("/dingtalk-identity-candidates/candidate-1")) {
        return response({
          candidate: discoveryCandidate({
            identity_state: "restore_required",
            historical_identity: {
              id: "identity-history",
              status: "unbound",
              revision: 2,
              user_id: "user-1",
              username: "zmh",
              user_display_name: "庄慕焕",
              user_status: "enabled",
            },
          }),
        })
      }
      if (url.endsWith("/users/user-1/external-identities")) {
        return response(
          adminOverview(
            [],
            [
              adminDingTalkIdentity({
                identity_id: "identity-history",
                staff_id: "staff-001",
                nickname: "Historical DingTalk User",
                status: "unbound",
                revision: 2,
              }),
            ]
          )
        )
      }
      if (url.endsWith("/users/user-1")) {
        return response({ user: user() })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderDetail("/users/user-1?candidate=candidate-1")

    const history = await screen.findByTestId("external-identity-history")
    await waitFor(() => expect(history).toHaveAttribute("open"))
    expect(
      await screen.findByRole("heading", { name: "确认受信钉钉候选" })
    ).toBeVisible()
    expect(
      screen.getByRole("button", { name: "确认绑定并保存授权" })
    ).toBeVisible()
  })

  it("uses only server-loaded candidate fields for trusted binding and keeps failures open", async () => {
    let bindingBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.includes("/api/admin/authorization/roles?"))
        return response(assignableRoles())
      if (url.endsWith("/dingtalk-identity-candidates/candidate-1")) {
        return response({ candidate: discoveryCandidate() })
      }
      if (
        url.endsWith("/dingtalk-identity-candidates/candidate-1/bind") &&
        init?.method === "POST"
      ) {
        bindingBody = JSON.parse(String(init.body))
        return response(
          {
            detail: {
              code: "revision_conflict",
              message: "候选信息已发生变化，请刷新后重试",
            },
          },
          409
        )
      }
      if (url.endsWith("/users/user-1/external-identities"))
        return response(adminOverview())
      if (url.endsWith("/users/user-1")) return response({ user: user() })
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail("/users/user-1?candidate=candidate-1")

    expect(
      await screen.findByRole("heading", { name: "确认受信钉钉候选" })
    ).toBeInTheDocument()
    expect(await screen.findByText("默认钉钉企业")).toBeInTheDocument()
    expect(await screen.findByText("corp-default")).toBeInTheDocument()
    expect(await screen.findByText("默认钉钉 Stream")).toBeInTheDocument()
    expect(await screen.findByText("staff-001")).toBeInTheDocument()
    expect(await screen.findByText("待绑定张三")).toBeInTheDocument()
    expect(screen.queryByLabelText("senderStaffId")).toBeNull()

    fireEvent.click(screen.getByRole("checkbox", { name: /诊断角色 1/ }))
    fireEvent.click(screen.getByRole("checkbox", { name: /诊断角色 2/ }))
    fireEvent.click(screen.getByRole("button", { name: "确认绑定并保存授权" }))
    expect(
      await screen.findByText("候选信息已发生变化，请刷新后重试")
    ).toBeInTheDocument()
    expect(bindingBody).toEqual({
      target_user_id: "user-1",
      expected_candidate_revision: 2,
      expected_user_revision: 3,
      initial_role_ids: ["role-1", "role-2"],
      bind_without_access_confirmed: false,
      replace_current_confirmed: false,
    })
    for (const forbidden of [
      "tenant_code",
      "external_subject_id",
      "connector_id",
      "display_name",
    ]) {
      expect(bindingBody).not.toHaveProperty(forbidden)
    }
    expect(
      screen.getByRole("heading", { name: "确认受信钉钉候选" })
    ).toBeInTheDocument()
  })

  it("prefills a new person from the candidate and preserves the candidate context", async () => {
    const requestedUrls: string[] = []
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      requestedUrls.push(url)
      if (url.endsWith("/dingtalk-identity-candidates/candidate-1")) {
        return response({ candidate: discoveryCandidate() })
      }
      if (url.endsWith("/api/admin/users") && init?.method === "POST") {
        return response({
          user: user({
            id: "user-new",
            username: "new-person",
            display_name: "待绑定张三",
          }),
        })
      }
      if (url.includes("/api/admin/users?")) {
        return response({
          users: [],
          pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
        })
      }
      if (url.endsWith("/users/user-new")) {
        return response({
          user: user({
            id: "user-new",
            username: "new-person",
            display_name: "待绑定张三",
          }),
        })
      }
      if (url.endsWith("/users/user-new/external-identities"))
        return response({ user_id: "user-new", current: [], history: [] })
      if (url.includes("/api/admin/authorization/roles?"))
        return response(emptyRoles())
      throw new Error(`Unexpected request: ${url}`)
    })
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })
    render(
      <QueryClientProvider client={client}>
        <AuthenticatedUserProvider user={authenticatedUser()}>
          <MemoryRouter initialEntries={["/users?candidate=candidate-1"]}>
            <Routes>
              <Route path="/users" element={<UsersPage />} />
              <Route path="/users/:userId" element={<UserDetailPage />} />
            </Routes>
          </MemoryRouter>
        </AuthenticatedUserProvider>
      </QueryClientProvider>
    )

    expect(await screen.findByText("请选择要绑定的人员")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "新建用户" }))
    expect(screen.getByLabelText("显示名称")).toHaveValue("待绑定张三")
    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "new-person" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建用户" }))

    expect(
      await screen.findByRole("heading", { name: "确认受信钉钉候选" })
    ).toBeInTheDocument()
    expect(
      requestedUrls.filter((url) =>
        url.endsWith("/dingtalk-identity-candidates/candidate-1")
      ).length
    ).toBeGreaterThanOrEqual(1)
  })

  it("shows a stable revision conflict instead of overwriting newer user data", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.includes("/api/admin/authorization/roles?"))
        return response(emptyRoles())
      if (url.endsWith("/users/user-1") && init?.method === "PUT") {
        return response(
          {
            detail: {
              code: "revision_conflict",
              message: "用户信息已被修改，请刷新后重试",
            },
          },
          409
        )
      }
      if (url.endsWith("/users/user-1/external-identities"))
        return response(adminOverview())
      if (url.endsWith("/users/user-1")) return response({ user: user() })
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail()
    fireEvent.change(await screen.findByLabelText("显示名称"), {
      target: { value: "并发覆盖尝试" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存资料" }))
    expect(
      await screen.findByText("用户信息已被修改，请刷新后重试")
    ).toBeInTheDocument()
  })

  it("uses governance mode when an administrator opens their own user detail", async () => {
    const requestedUrls: string[] = []
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      requestedUrls.push(url)
      if (url.includes("/api/admin/authorization/roles?"))
        return response(emptyRoles())
      if (url.endsWith("/users/user-1/external-identities"))
        return response(adminOverview([adminDingTalkIdentity()]))
      if (url.endsWith("/users/user-1")) return response({ user: user() })
      throw new Error(`Unexpected request: ${url}`)
    })

    renderDetail(
      "/users/user-1",
      authenticatedUser({ id: "user-1", username: "zmh" })
    )

    expect(await screen.findByText("钉钉身份")).toBeInTheDocument()
    expect(
      await screen.findByRole("button", { name: "停用身份" })
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "解绑" })).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "从受信候选绑定钉钉" })
    ).toBeInTheDocument()
    expect(screen.queryByRole("textbox", { name: "租户 / 实例" })).toBeNull()
    expect(screen.queryByRole("textbox", { name: "外部主体" })).toBeNull()
    expect(
      requestedUrls.some((url) =>
        url.endsWith("/users/user-1/external-identities")
      )
    ).toBe(true)
    expect(
      requestedUrls.some((url) => url.endsWith("/api/me/external-identities"))
    ).toBe(false)
  })

  it("keeps DingTalk read-only on the dedicated self-service route", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/api/me/external-identities")) {
        return response(selfOverview([selfDingTalkIdentity({ nickname: "" })]))
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderMyExternalIdentities()

    expect(await screen.findByText("ONES 本人身份")).toBeInTheDocument()
    expect(await screen.findByText("钉钉身份")).toBeInTheDocument()
    expect(await screen.findByText("钉钉未返回昵称")).toBeInTheDocument()
    expect(await screen.findByText("已启用 · 只读")).toBeInTheDocument()
    const identityDetails = screen.getByText("身份详情")
    identityDetails.focus()
    expect(identityDetails).toHaveFocus()
    expect(identityDetails.closest("details")).toBeInTheDocument()
    expect(identityDetails.closest("details")?.querySelector("dl")).toHaveClass(
      "grid",
      "sm:grid-cols-2"
    )
    expect(screen.queryByRole("button", { name: "停用身份" })).toBeNull()
    expect(screen.queryByRole("button", { name: "解绑" })).toBeNull()
  })

  it("submits only ONES email/password in self mode and clears password after a failed request", async () => {
    let bindingBody: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (
        url.endsWith("/api/me/external-identities") &&
        (!init?.method || init.method === "GET")
      ) {
        return response(selfOverview())
      }
      if (url.endsWith("/ones/challenges") && init?.method === "POST") {
        bindingBody = JSON.parse(String(init.body))
        return response(
          {
            detail: {
              code: "ones_invalid_credentials",
              message: "ONES 邮箱或密码错误",
            },
          },
          400
        )
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderMyExternalIdentities()
    await screen.findByText("ONES 本人身份")
    fireEvent.click(await screen.findByRole("button", { name: "绑定 ONES" }))
    fireEvent.change(screen.getByLabelText("ONES 邮箱"), {
      target: { value: "zmh@example.test" },
    })
    const password = screen.getByLabelText("一次性验证密码")
    fireEvent.change(password, { target: { value: "ones-password" } })
    fireEvent.click(screen.getByRole("button", { name: "验证并读取 Team" }))

    expect(await screen.findByText("ONES 邮箱或密码错误")).toBeInTheDocument()
    expect(bindingBody).toEqual({
      email: "zmh@example.test",
      password: "ones-password",
    })
    expect(password).toHaveValue("")
    for (const forbidden of ["uuid", "token", "url", "metadata", "team"]) {
      expect(bindingBody).not.toHaveProperty(forbidden)
    }
  })

  it("completes two-phase self binding and saves one verified default Team", async () => {
    let confirmBody: Record<string, unknown> | undefined
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input, init) => {
        const url = String(input)
        if (
          url.endsWith("/api/me/external-identities") &&
          (!init?.method || init.method === "GET")
        ) {
          return response(selfOverview())
        }
        if (url.endsWith("/ones/challenges") && init?.method === "POST") {
          return response({
            challenge: {
              id: "challenge-1",
              provider: "ones",
              external_user_id: "ones-user-1",
              display_name: "庄慕焕",
              teams: [
                { id: "team-a", name: "Team A" },
                { id: "team-b", name: "Team B" },
              ],
              team_ids: ["team-a", "team-b"],
              verified_at: "2026-07-31T00:00:00Z",
              expires_at: "2026-08-01T00:00:00Z",
              status: "PENDING",
              created_at: "2026-07-31T00:00:00Z",
            },
          })
        }
        if (url.endsWith("/ones/confirm") && init?.method === "POST") {
          confirmBody = JSON.parse(String(init.body))
          return response({
            user: { id: "user-1", display_name: "庄慕焕" },
            ones: selfOnesIdentity({
              user_name: "庄慕焕",
              user_id: "ones-user-1",
              default_team: { id: "team-b", name: "Team B" },
              teams: [
                { id: "team-a", name: "Team A" },
                { id: "team-b", name: "Team B" },
              ],
            }),
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      })

    renderMyExternalIdentities()
    const bindButton = await screen.findByRole("button", { name: "绑定 ONES" })
    await waitFor(() => expect(bindButton).toBeEnabled())
    fireEvent.click(bindButton)
    fireEvent.change(screen.getByLabelText("ONES 邮箱"), {
      target: { value: "zmh@example.test" },
    })
    fireEvent.change(screen.getByLabelText("一次性验证密码"), {
      target: { value: "ones-password" },
    })
    fireEvent.click(screen.getByRole("button", { name: "验证并读取 Team" }))
    const team = await screen.findByLabelText("默认 Team")
    fireEvent.change(team, { target: { value: "team-b" } })
    fireEvent.click(screen.getByRole("button", { name: "保存绑定" }))

    await waitFor(() =>
      expect(confirmBody).toEqual({
        challenge_id: "challenge-1",
        default_team_id: "team-b",
        replace_existing: false,
      })
    )
    expect(
      fetch.mock.calls.some((call) =>
        String(call[0]).includes("/api/admin/users")
      )
    ).toBe(false)
  })

  it("changes identity state, confirms soft unbind, and disables personal binding for service accounts", async () => {
    let currentIdentity = adminDingTalkIdentity()
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((input, init) => {
        const url = String(input)
        if (url.includes("/api/admin/authorization/roles?"))
          return response(emptyRoles())
        if (
          url.includes("/identities/identity-1/status") &&
          init?.method === "PUT"
        ) {
          currentIdentity = adminDingTalkIdentity({
            status: "disabled",
            revision: 2,
          })
          return response({
            identity: { id: "identity-1", status: "disabled", revision: 2 },
          })
        }
        if (
          url.includes("/identities/identity-1?") &&
          init?.method === "DELETE"
        ) {
          currentIdentity = adminDingTalkIdentity({
            status: "unbound",
            revision: 3,
          })
          return response({
            identity: { id: "identity-1", status: "unbound", revision: 3 },
          })
        }
        if (url.endsWith("/users/user-1/external-identities"))
          return response(
            currentIdentity.status === "unbound"
              ? adminOverview([], [currentIdentity])
              : adminOverview([currentIdentity])
          )
        if (url.endsWith("/users/user-1")) return response({ user: user() })
        throw new Error(`Unexpected request: ${url}`)
      })
    const firstRender = renderDetail()
    fireEvent.click(await screen.findByRole("button", { name: "停用身份" }))
    await waitFor(() =>
      expect(
        fetch.mock.calls.some((call) => String(call[0]).includes("/status"))
      ).toBe(true)
    )
    fireEvent.click(await screen.findByRole("button", { name: "解绑" }))
    fireEvent.click(screen.getByRole("button", { name: "确认解绑" }))
    await waitFor(() =>
      expect(
        fetch.mock.calls.some((call) =>
          String(call[0]).includes("?expected_revision=2")
        )
      ).toBe(true)
    )

    firstRender.unmount()
    vi.restoreAllMocks()
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.includes("/api/admin/authorization/roles?"))
        return response(emptyRoles())
      if (url.endsWith("/users/user-1/external-identities"))
        return response(adminOverview())
      if (url.endsWith("/users/user-1"))
        return response({ user: user({ account_type: "service" }) })
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail()
    expect(
      await screen.findByRole("button", { name: "从受信候选绑定钉钉" })
    ).toBeDisabled()
    expect(screen.queryByRole("button", { name: /ONES.*绑定/ })).toBeNull()
    expect(
      screen.getByText("服务账号不能绑定个人外部身份。")
    ).toBeInTheDocument()
  })
})
