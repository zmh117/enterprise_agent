import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { App } from "@/App"

describe("Agent 应用平台静态原型", () => {
  it("展示目标导航、业务应用、调用链和外部身份", () => {
    render(<App />)

    expect(screen.getAllByText("Agent 应用平台").length).toBeGreaterThan(0)
    expect(screen.getAllByText("钉钉私聊诊断助手").length).toBeGreaterThan(0)
    expect(screen.getAllByText("钉钉群聊诊断助手").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Webhook 告警分析助手").length).toBeGreaterThan(
      0
    )
    expect(screen.getByText("Capability Gateway")).toBeInTheDocument()
    expect(screen.getByText("API Platform")).toBeInTheDocument()
    expect(screen.getByText("ONES身份")).toBeInTheDocument()
    expect(screen.getByText("身份关联不等于授权")).toBeInTheDocument()
  })

  it("不保留旧模板业务文案", () => {
    const { container } = render(<App />)
    const page = container.textContent ?? ""

    for (const legacyText of [
      "Acme",
      "Revenue",
      "Visitors",
      "Documents",
      "Projects",
      "Lifecycle",
    ]) {
      expect(page).not.toContain(legacyText)
    }
  })

  it("加载和渲染不产生网络或流式连接", () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new Error("not expected"))
    const xhrOpenSpy = vi.spyOn(XMLHttpRequest.prototype, "open")
    const websocketSpy = vi.fn()
    const eventSourceSpy = vi.fn()
    vi.stubGlobal("WebSocket", websocketSpy)
    vi.stubGlobal("EventSource", eventSourceSpy)

    render(<App />)

    expect(fetchSpy).not.toHaveBeenCalled()
    expect(xhrOpenSpy).not.toHaveBeenCalled()
    expect(websocketSpy).not.toHaveBeenCalled()
    expect(eventSourceSpy).not.toHaveBeenCalled()
  })

  it("所有业务命令保持禁用且没有成功反馈", () => {
    const { container } = render(<App />)
    const disabledButtons = Array.from(
      container.querySelectorAll("button:disabled")
    )

    expect(disabledButtons.length).toBeGreaterThanOrEqual(12)
    for (const button of disabledButtons) {
      expect(button).toHaveAttribute("disabled")
      expect(button).toHaveAttribute("title")
    }
    expect(container.textContent).not.toMatch(
      /保存成功|发布成功|绑定成功|测试成功/
    )
  })

  it("不暴露底层连接配置、凭据或可执行入口", () => {
    const { container } = render(<App />)
    const page = container.textContent ?? ""

    for (const forbiddenEntry of [
      "数据库连接",
      "缓存地址",
      "日志平台地址",
      "连接字符串",
      "凭据 URI",
      "AppSecret",
      "Webhook Secret",
      "执行 Shell",
      "执行任意请求",
    ]) {
      expect(page).not.toContain(forbiddenEntry)
    }
    expect(screen.getByText("MVP 安全边界")).toBeInTheDocument()
    expect(screen.getAllByText("原型数据").length).toBeGreaterThan(0)
  })
})
