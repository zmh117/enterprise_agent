import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { KnowledgeOperationsPanel } from "./knowledge-operations-panel"
import type { KnowledgeOperationsSnapshot } from "../domain/knowledge-operations"
import { operationsSchema } from "../domain/knowledge-operations"

function fixture(): KnowledgeOperationsSnapshot {
  const runtime = {
    online: true,
    observed_at: "2026-11-03T10:00:00Z",
    snapshot: {},
  }
  return {
    controller: {
      ...runtime,
      snapshot: {
        services: [
          { name: "knowledge-mcp", state: "running", health: "healthy" },
        ],
      },
    },
    sync_worker: runtime,
    deployment: {
      ...runtime,
      snapshot: { built_version: "build-v2", running_version: "build-v1" },
    },
    operations: [],
    plans: [
      {
        id: "plan",
        code: "MES ONES",
        revision: 3,
        enabled: true,
        schedule_enabled: true,
        interval_seconds: 14400,
        next_run_at: "2026-11-03T14:00:00Z",
        last_success_at: "2026-11-03T10:00:00Z",
        first_day: "2024-01-01",
        run: null,
        bases: ["缺陷", "需求", "工单"].map((code, i) => ({
          code,
          kind: String(i),
          knowledge_base_id: String(i),
          metrics: null,
        })),
      },
    ],
  }
}
function setup({
  canManage = true,
  data = fixture(),
  eventDetails = {
    step: 11,
    build_action: "install_python_dependencies",
    stage_step: 4,
    stage_total: 11,
  } as Record<string, string | number>,
} = {}) {
  const calls: { url: string; body: Record<string, unknown> }[] = []
  const fetch = vi.fn(
    async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input)
      if (url.includes("/events"))
        return Response.json({
          events: [
            {
              id: "event",
              operation_id: "operation",
              service: "knowledge-embedding",
              code: "build_step",
              created_at: "2026-11-03T10:00:00Z",
              details: eventDetails,
            },
          ],
          cursor: "cursor",
        })
      const body = JSON.parse(String(init.body ?? "{}"))
      calls.push({ url, body })
      if (url.endsWith("/schedule"))
        return Response.json({
          ...data.plans[0],
          schedule_enabled: body.enabled,
        })
      return Response.json(
        {
          id: "operation",
          kind: body.kind,
          binding_id: body.binding_id ?? null,
          state: "QUEUED",
          stage: "queued",
          run_id: null,
          attempts: 0,
          error_code: null,
          created_at: "2026-11-03T10:00:00Z",
          updated_at: "2026-11-03T10:00:00Z",
          parameters: { first_day: body.first_day, last_day: body.last_day },
        },
        { status: 202 }
      )
    }
  )
  vi.stubGlobal("fetch", fetch)
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <KnowledgeOperationsPanel
        data={data}
        error={null}
        canManage={canManage}
        onRefresh={() => {}}
      />
    </QueryClientProvider>
  )
  return { calls, fetch }
}

describe("知识库运维", () => {
  it("HTTP 环境没有 randomUUID 时仍能同步，失败重试复用同一幂等键", async () => {
    const browserCrypto = globalThis.crypto
    vi.stubGlobal("crypto", {
      getRandomValues: browserCrypto.getRandomValues.bind(browserCrypto),
    })
    try {
      const { calls, fetch } = setup()
      fetch.mockRejectedValueOnce(new TypeError("synthetic network failure"))
      fireEvent.click(screen.getByRole("button", { name: "立即同步" }))
      expect(fetch).not.toHaveBeenCalled()
      fireEvent.click(screen.getByRole("button", { name: "确认执行" }))
      await screen.findByRole("alert")
      expect(fetch).toHaveBeenCalledTimes(1)
      const first = JSON.parse(String(fetch.mock.calls[0][1]?.body))
      expect(first).toMatchObject({ kind: "sync", binding_id: "plan" })
      expect(first.request_key).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
      )
      fireEvent.click(screen.getByRole("button", { name: "确认执行" }))
      await waitFor(() => expect(calls).toHaveLength(1))
      expect(calls[0].body).toEqual(first)
      await screen.findByText("任务进度与日志")
    } finally {
      vi.stubGlobal("crypto", browserCrypto)
    }
  })

  it("运行中的四小时计划显示完成后间隔，暂停后不承诺下次自动执行", () => {
    const data = fixture()
    data.plans.push({
      ...data.plans[0],
      id: "paused",
      code: "paused",
      schedule_enabled: false,
      next_run_at: null,
    })
    data.operations = data.plans.map((plan) => ({
      id: `operation-${plan.id}`,
      kind: "sync",
      binding_id: plan.id,
      state: "RUNNING",
      stage: "started",
      run_id: "run",
      attempts: 1,
      error_code: null,
      created_at: "2026-11-03T10:00:00Z",
      updated_at: "2026-11-03T10:00:00Z",
      parameters: {},
    }))
    setup({ data })
    expect(screen.getAllByText(/每 4 小时执行/)).toHaveLength(2)
    expect(screen.getAllByText(/下次执行：本轮完成后 4 小时/)).toHaveLength(1)
    expect(screen.queryByText(/本轮完成后 1 小时/)).not.toBeInTheDocument()
  })

  it.each([
    {
      progress: { processed: 2, total: 5, encoded: 1, reused: 1, verified: 2 },
      expected: "已完成 2 / 5 块 · 新生成向量 1 块 · 复用已有向量 1 块",
    },
    {
      progress: { verified: 1, encoded: 1, reused: 0 },
      expected:
        "已完成 1 块 · 总块数待上报 · 新生成向量 1 块 · 复用已有向量 0 块",
    },
    {
      progress: {},
      expected: "已完成块数待上报 · 总块数待上报",
    },
    {
      progress: { processed: 0, total: 0, encoded: 0, reused: 0 },
      expected: "已完成 0 / 0 块 · 新生成向量 0 块 · 复用已有向量 0 块",
    },
  ])("按已上报的块数显示文档进度：$expected", ({ progress, expected }) => {
    const data = fixture()
    data.plans[0].run = {
      run_id: "run",
      phase: "CHUNKING",
      active: true,
      error_code: null,
      updated_at: "2026-11-03T10:00:00Z",
      progress: { phase: "indexing", ...progress },
    }
    setup({ data: operationsSchema.parse(data) })
    expect(
      screen.getByText(`当前文档向量处理：${expected}`)
    ).toBeInTheDocument()
    expect(screen.queryByText(/0 \/ 未知/)).not.toBeInTheDocument()
  })

  it("停止服务明确影响全部知识库，确认后提交任务", async () => {
    const { calls } = setup()
    fireEvent.click(screen.getByRole("button", { name: "停止服务" }))
    expect(screen.getByText(/采集断点、数据和模型保留/)).toBeInTheDocument()
    expect(calls).toHaveLength(0)
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body.kind).toBe("stop")
    expect(calls[0].body.request_key).toBeTruthy()
    expect(calls[0].body).not.toHaveProperty("command")
    await screen.findByText("任务进度与日志")
  })

  it("补采展示三库范围并提交固定日期", async () => {
    const randomUUID = vi.spyOn(crypto, "randomUUID").mockImplementation(() => {
      throw new Error("randomUUID must not be required for backfill")
    })
    const { calls } = setup()
    fireEvent.click(screen.getByRole("button", { name: "日期补采" }))
    expect(screen.getByText(/范围：缺陷、需求、工单/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("起始日期"), {
      target: { value: "2024-01-02" },
    })
    fireEvent.change(screen.getByLabelText("结束日期"), {
      target: { value: "2024-01-20" },
    })
    fireEvent.click(screen.getByRole("button", { name: "提交补采" }))
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toMatchObject({
      kind: "backfill",
      binding_id: "plan",
      first_day: "2024-01-02",
      last_day: "2024-01-20",
    })
    expect(randomUUID).not.toHaveBeenCalled()
  })

  it("暂停自动同步使用计划开关，不停止容器或停用资源", async () => {
    const { calls } = setup()
    fireEvent.click(screen.getByRole("button", { name: "暂停自动同步" }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toEqual({
      url: "/api/platform/knowledge/operations/plans/plan/schedule",
      body: { enabled: false, expected_revision: 3 },
    })
  })

  it("只读权限可看状态和日志，不能发起运维", () => {
    setup({ canManage: false })
    expect(
      screen.queryByRole("button", { name: "构建镜像" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "日期补采" })
    ).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "查看统一日志" })).toBeEnabled()
  })

  it("执行器离线时保留未知状态，不声称检索已停止", () => {
    const data = fixture()
    data.controller.online = false
    setup({ data })
    expect(screen.getByText("检索服务：未知")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "启动 / 应用版本" })
    ).toBeDisabled()
    expect(screen.getByText(/不会推断知识服务已停止/)).toBeInTheDocument()
  })

  it("旧记录只说明已知编号，不推测具体操作", async () => {
    setup({ eventDetails: { step: 11 } })
    fireEvent.click(screen.getByRole("button", { name: "查看统一日志" }))
    await screen.findByText("步骤 11：此历史记录未保存具体操作")
    expect(screen.queryByText(/当前构建阶段/)).not.toBeInTheDocument()
  })

  it("按服务筛选安全事件", async () => {
    const { fetch } = setup()
    fireEvent.click(screen.getByRole("button", { name: "查看统一日志" }))
    await screen.findByText("步骤 11：安装 Python 依赖")
    expect(screen.getByText("当前构建阶段：第 4 / 11 步")).toBeInTheDocument()
    expect(screen.queryByText("step：11")).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("筛选日志服务"), {
      target: { value: "knowledge-sync" },
    })
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) =>
          String(url).includes("service=knowledge-sync")
        )
      ).toBe(true)
    )
  })
})
