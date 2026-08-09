import { fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AuthenticationGate } from "@/contexts/auth/presentation/authentication-gate"
import {
  useAuthenticatedUser,
  useLogout,
} from "@/contexts/auth/presentation/authenticated-user-state"

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

const user = {
  id: "user_local_admin",
  username: "local-user",
  display_name: "Local Administrator",
  roles: ["platform-admin"],
  auth_source: "local",
  capabilities: { users_manage: true },
}

function CurrentUserProbe() {
  const currentUser = useAuthenticatedUser()
  return <div>当前用户：{currentUser.id}</div>
}

function LogoutProbe() {
  const logout = useLogout()
  return <button onClick={() => void logout()}>退出测试账户</button>
}

function renderGate(
  children: React.ReactNode,
  queryClient = new QueryClient()
) {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthenticationGate>{children}</AuthenticationGate>
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("AuthenticationGate", () => {
  it("shows login for an anonymous session and opens the platform after login", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementationOnce(() =>
        response({ detail: "Authentication required" }, 401)
      )
      .mockImplementationOnce(() => response({ user }))

    renderGate(<div>管理控制面</div>)

    expect(
      await screen.findByRole("heading", { name: "登录 Agent 控制台" })
    ).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "local-user" },
    })
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "local-admin-change-me" },
    })
    fireEvent.click(screen.getByRole("button", { name: "登录" }))

    expect(await screen.findByText("管理控制面")).toBeInTheDocument()
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      })
    )
  })

  it("renders the platform immediately when the session is valid", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => response({ user }))

    renderGate(<div>管理控制面</div>)

    expect(await screen.findByText("管理控制面")).toBeInTheDocument()
    expect(
      screen.queryByRole("heading", { name: "登录 Agent 控制台" })
    ).not.toBeInTheDocument()
    expect(screen.getByText("管理控制面")).toBeInTheDocument()
  })

  it("provides the authenticated user to protected descendants", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => response({ user }))

    renderGate(<CurrentUserProbe />)

    expect(await screen.findByText(`当前用户：${user.id}`)).toBeInTheDocument()
  })

  it("ends the protected session and clears cached data after logout", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response({ user }))
      .mockImplementationOnce(() => response({ status: "logged_out" }))
    const queryClient = new QueryClient()
    queryClient.setQueryData(["private-data"], { secret: true })

    renderGate(<LogoutProbe />, queryClient)

    fireEvent.click(await screen.findByRole("button", { name: "退出测试账户" }))

    expect(
      await screen.findByRole("heading", { name: "登录 Agent 控制台" })
    ).toBeInTheDocument()
    expect(queryClient.getQueryData(["private-data"])).toBeUndefined()
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/auth/logout",
      expect.objectContaining({ method: "POST", credentials: "include" })
    )
  })
})
