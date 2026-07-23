import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { AuthenticationGate } from "@/contexts/auth/presentation/authentication-gate"

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

describe("AuthenticationGate", () => {
  it("shows login for an anonymous session and opens the platform after login", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementationOnce(() =>
        response({ detail: "Authentication required" }, 401)
      )
      .mockImplementationOnce(() => response({ user }))

    render(
      <AuthenticationGate>
        <div>管理控制面</div>
      </AuthenticationGate>
    )

    expect(
      await screen.findByRole("heading", { name: "登录 Agent 应用平台" })
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

    render(
      <AuthenticationGate>
        <div>管理控制面</div>
      </AuthenticationGate>
    )

    expect(await screen.findByText("管理控制面")).toBeInTheDocument()
    expect(
      screen.queryByRole("heading", { name: "登录 Agent 应用平台" })
    ).not.toBeInTheDocument()
  })
})
