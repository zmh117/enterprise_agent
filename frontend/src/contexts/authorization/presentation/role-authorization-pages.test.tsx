import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  RoleAuthorizationPage,
  RoleDetailPage,
} from "@/contexts/authorization/presentation/role-authorization-pages"

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  )
}

const role = {
  id: "role-diagnostic",
  code: "diagnostic-operator",
  name: "诊断操作员",
  description: "只读诊断",
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
  application_count: 0,
}

function detail() {
  return {
    role,
    admin: { revision: 1, bindings: [], implicit_all: false },
    business: { revision: 1, applications: [] },
    membership: { revision: 1, members: [] },
  }
}

function capability(
  code: string,
  display_name_zh: string,
  risk_level: "low" | "medium" | "high",
  dependencies: string[] = [],
) {
  const [resource_type, action] = code.split(".")
  return {
    code,
    module: "applications",
    resource_type,
    resource_code: "*",
    action,
    display_name_zh,
    risk_level,
    dependencies,
    resource_scope_kind: "global",
    assignable: true,
  }
}

function renderDetail() {
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
      <MemoryRouter initialEntries={["/users/roles/role-diagnostic"]}>
        <Routes>
          <Route path="/users/roles/:roleId" element={<RoleDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function renderList() {
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
      <MemoryRouter initialEntries={["/users/roles"]}>
        <Routes>
          <Route path="/users/roles" element={<RoleAuthorizationPage />} />
          <Route
            path="/users/roles/:roleId"
            element={<div>角色详情已打开</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("角色授权中心", () => {
  it("从安全模板创建角色时只预填用途和说明", async () => {
    let submitted: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/api/admin/capabilities")) {
        return response({
          capabilities: [
            "authorization.read",
            "authorization.manage",
          ],
          modules: {},
        })
      }
      if (
        url.endsWith("/authorization/roles") &&
        init?.method === "POST"
      ) {
        submitted = JSON.parse(String(init.body))
        return response(detail())
      }
      if (url.includes("/api/admin/authorization/roles?")) {
        return response({
          items: [],
          page: { limit: 100, offset: 0, total: 0 },
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderList()

    const createButton = await screen.findByRole("button", {
      name: "新建角色",
    })
    await waitFor(() => expect(createButton).not.toBeDisabled())
    fireEvent.click(createButton)
    fireEvent.change(screen.getByLabelText("角色名称"), {
      target: { value: "应用诊断员" },
    })
    fireEvent.change(screen.getByLabelText(/^角色编码/), {
      target: { value: "app-diagnostic" },
    })
    fireEvent.change(screen.getByLabelText(/^起始模板/), {
      target: { value: "business_reader" },
    })
    fireEvent.click(screen.getByRole("button", { name: "创建角色" }))

    await waitFor(() =>
      expect(submitted).toEqual({
        name: "应用诊断员",
        code: "app-diagnostic",
        description: "用于配置业务应用、只读能力和明确的数据范围。",
        purpose_tags: ["业务访问"],
      }),
    )
    expect(await screen.findByText("角色详情已打开")).toBeInTheDocument()
  })

  it("无编辑权时只读展示授权区且不能提交", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith("/api/admin/capabilities")) {
        return response({
          capabilities: ["authorization.read"],
          modules: {},
        })
      }
      if (url.endsWith("/authorization/roles/role-diagnostic")) {
        return response(detail())
      }
      if (url.endsWith("/authorization/capabilities")) {
        return response({
          items: [
            capability("applications.read", "查看业务应用", "low"),
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail()

    expect(await screen.findByText("诊断操作员")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("tab", { name: "管理后台能力" }))
    expect(
      await screen.findByText(
        "当前账号只能查看此授权区，提交不会包含或覆盖这里的配置。",
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "原子保存后台能力" }),
    ).toBeDisabled()
    expect(
      fetch.mock.calls.some(
        ([, init]) => String(init?.method ?? "GET") !== "GET",
      ),
    ).toBe(false)
  })

  it("高风险能力自动联动查看依赖并原子提交中文确认", async () => {
    let submitted: Record<string, unknown> | undefined
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/api/admin/capabilities")) {
        return response({
          capabilities: [
            "authorization.read",
            "authorization.manage",
            "authorization.assign",
          ],
          modules: {},
        })
      }
      if (
        url.endsWith(
          "/authorization/roles/role-diagnostic/admin-capabilities",
        ) &&
        init?.method === "PUT"
      ) {
        submitted = JSON.parse(String(init.body))
        return response({
          revision: 2,
          bindings: [
            {
              capability_code: "applications.read",
              resource_type: "business_application",
              resource_code: "*",
            },
            {
              capability_code: "applications.publish",
              resource_type: "business_application",
              resource_code: "*",
            },
          ],
        })
      }
      if (url.endsWith("/authorization/roles/role-diagnostic")) {
        return response(detail())
      }
      if (url.endsWith("/authorization/capabilities")) {
        return response({
          items: [
            capability("applications.read", "查看业务应用", "low"),
            capability(
              "applications.publish",
              "发布业务应用",
              "high",
              ["applications.read"],
            ),
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail()

    await screen.findByText("诊断操作员")
    fireEvent.click(screen.getByRole("tab", { name: "管理后台能力" }))
    fireEvent.click(
      await screen.findByRole("checkbox", { name: /发布业务应用/ }),
    )
    expect(
      screen.getByRole("checkbox", { name: /查看业务应用/ }),
    ).toHaveAttribute("data-checked")
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /我已确认本次高风险授权变更/,
      }),
    )
    fireEvent.change(screen.getByLabelText("授权变更原因"), {
      target: { value: "发布职责委派" },
    })
    fireEvent.click(
      screen.getByRole("button", { name: "原子保存后台能力" }),
    )

    await waitFor(() =>
      expect(submitted).toEqual({
        expected_revision: 1,
        bindings: [
          {
            capability_code: "applications.publish",
            resource_code: "*",
          },
          {
            capability_code: "applications.read",
            resource_code: "*",
          },
        ],
        confirmed: true,
        reason: "发布职责委派",
      }),
    )
  })

  it("分区 revision 冲突保留本地草稿并触发未保存离开保护", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input)
      if (url.endsWith("/api/admin/capabilities")) {
        return response({
          capabilities: [
            "authorization.read",
            "authorization.manage",
          ],
          modules: {},
        })
      }
      if (
        url.endsWith(
          "/authorization/roles/role-diagnostic/admin-capabilities",
        ) &&
        init?.method === "PUT"
      ) {
        return response(
          {
            detail: {
              code: "revision_conflict",
              message: "角色配置已被其他管理员更新，请刷新后重试",
              field_errors: [],
              correlation_id: "corr-role-conflict",
            },
          },
          409,
        )
      }
      if (url.endsWith("/authorization/roles/role-diagnostic")) {
        return response(detail())
      }
      if (url.endsWith("/authorization/capabilities")) {
        return response({
          items: [
            capability("applications.read", "查看业务应用", "low"),
          ],
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderDetail()

    await screen.findByText("诊断操作员")
    fireEvent.click(screen.getByRole("tab", { name: "管理后台能力" }))
    fireEvent.click(
      await screen.findByRole("checkbox", { name: /查看业务应用/ }),
    )
    const beforeUnload = new Event("beforeunload", { cancelable: true })
    window.dispatchEvent(beforeUnload)
    expect(beforeUnload.defaultPrevented).toBe(true)
    fireEvent.click(
      screen.getByRole("button", { name: "原子保存后台能力" }),
    )

    expect(
      await screen.findByText("角色配置已被其他管理员更新，请刷新后重试"),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("checkbox", { name: /查看业务应用/ }),
    ).toHaveAttribute("data-checked")
  })

  it.each([
    [
      "legacy_compatible",
      true,
      "当前由旧授权兼容链路允许，建议迁移到业务角色。",
      "旧授权兼容模式",
    ],
    [
      "application_capability_safety_ceiling",
      false,
      "所选能力超出业务应用和只读工具安全上限，角色不能授予。",
      "",
    ],
    [
      "explicit_application_deny",
      false,
      "高级显式拒绝覆盖了角色允许。",
      "",
    ],
  ])(
    "权限模拟安全展示 %s 决策",
    async (reason, allowed, message, marker) => {
      vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
        const url = String(input)
        if (url.endsWith("/api/admin/capabilities")) {
          return response({
            capabilities: ["authorization.read"],
            modules: {},
          })
        }
        if (url.endsWith("/authorization/roles/role-diagnostic")) {
          return response(detail())
        }
        if (url.includes("/api/admin/users?")) {
          return response({
            users: [
              {
                id: "user-test",
                username: "test-user",
                display_name: "测试用户",
                email: "",
                status: "enabled",
                account_type: "human",
                revision: 1,
                created_at: "2026-07-26T00:00:00Z",
                updated_at: "2026-07-26T00:00:00Z",
              },
            ],
            pagination: {
              page: 1,
              page_size: 100,
              total: 1,
              total_pages: 1,
            },
          })
        }
        if (url.endsWith("/authorization/assignable-catalog")) {
          return response({
            applications: [
              {
                id: "app-test",
                code: "diagnostic-app",
                name: "诊断应用",
                description: "",
                project_code: "default",
                status: "enabled",
                capabilities: [],
              },
            ],
            topology: [],
            scope_mode: "explicit_current_set",
            scope_notice: "当前全部保存明确集合",
          })
        }
        if (
          url.endsWith("/authorization/explanations") &&
          init?.method === "POST"
        ) {
          return response({
            decision: {
              allowed,
              stage: "invoke",
              reason,
              source_role_codes: ["diagnostic-operator"],
              application: { id: "app-test", code: "diagnostic-app" },
              capability_code: "",
              scope: {},
              legacy_compatible: reason === "legacy_compatible",
            },
            notice: "只显示安全摘要",
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      })
      renderDetail()

      await screen.findByText("诊断操作员")
      fireEvent.click(screen.getByRole("tab", { name: "有效权限预览" }))
      fireEvent.change(await screen.findByLabelText("用户"), {
        target: { value: "user-test" },
      })
      fireEvent.change(screen.getByLabelText("业务应用"), {
        target: { value: "app-test" },
      })
      fireEvent.click(screen.getByRole("button", { name: "模拟授权决策" }))

      expect(await screen.findByText(message)).toBeInTheDocument()
      if (marker) expect(screen.getByText(new RegExp(marker))).toBeInTheDocument()
    },
  )
})
