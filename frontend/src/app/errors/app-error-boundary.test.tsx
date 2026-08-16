import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { AppErrorBoundary } from "@/app/errors/app-error-boundary"


function BrokenPage(): never {
  throw new Error("sensitive-render-detail-must-not-be-visible")
}

describe("AppErrorBoundary", () => {
  it("用安全恢复页替代渲染异常且不显示异常详情", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined)

    const { container } = render(
      <AppErrorBoundary>
        <BrokenPage />
      </AppErrorBoundary>
    )

    expect(screen.getByText("管理页面暂时无法显示")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "刷新页面" })).toBeInTheDocument()
    expect(container.textContent).not.toContain(
      "sensitive-render-detail-must-not-be-visible"
    )
  })
})
