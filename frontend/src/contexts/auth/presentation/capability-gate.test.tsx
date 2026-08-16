import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AUTHENTICATION_REQUIRED_EVENT } from "@/contexts/auth/application/auth-session-events"
import { CapabilityGate } from "@/contexts/auth/presentation/capability-gate"


function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  )
}

function renderGate() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })
      }
    >
      <MemoryRouter>
        <CapabilityGate capability="jobs.read">
          <div>受保护内容</div>
        </CapabilityGate>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("CapabilityGate", () => {
  it("只在成功响应缺少 capability 时显示无权限", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({ capabilities: [], modules: {} })
    )

    renderGate()

    expect(await screen.findByText("无权访问此页面")).toBeInTheDocument()
    expect(screen.queryByText("管理服务不可用")).not.toBeInTheDocument()
  })

  it("把明确的 403 显示为无权限", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({ detail: "forbidden" }, 403)
    )

    renderGate()

    expect(await screen.findByText("无权访问此页面")).toBeInTheDocument()
  })

  it.each([
    ["server", () => response({ detail: "failed" }, 500)],
    ["network", () => Promise.reject(new Error("network failed"))],
    ["schema", () => response({ capabilities: "invalid", modules: {} })],
  ])("把 %s 错误显示为可重试的服务故障", async (_name, fetcher) => {
    vi.spyOn(globalThis, "fetch").mockImplementation(fetcher)

    renderGate()

    expect(await screen.findByText("管理服务不可用")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "重新校验" })).toBeInTheDocument()
    expect(screen.queryByText("无权访问此页面")).not.toBeInTheDocument()
  })

  it("服务恢复后可重新校验并显示内容", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response({ detail: "failed" }, 500))
      .mockImplementationOnce(() =>
        response({ capabilities: ["jobs.read"], modules: {} })
      )
    renderGate()
    fireEvent.click(await screen.findByRole("button", { name: "重新校验" }))

    expect(await screen.findByText("受保护内容")).toBeInTheDocument()
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it("401 通知 AuthenticationGate 重新确认登录状态", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      response({ detail: "unauthenticated" }, 401)
    )
    const listener = vi.fn()
    window.addEventListener(AUTHENTICATION_REQUIRED_EVENT, listener)

    renderGate()

    expect(await screen.findByText("登录状态已失效")).toBeInTheDocument()
    await waitFor(() => expect(listener).toHaveBeenCalledTimes(1))
    window.removeEventListener(AUTHENTICATION_REQUIRED_EVENT, listener)
  })
})
