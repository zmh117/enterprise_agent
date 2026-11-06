import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CodeKnowledgePanel } from "./code-knowledge-panel"

const data = {
  components: {
    backend: "set_server",
    factory_frontend: "set_web/EBR",
    group_frontend: "set_web/JTH",
  },
  sources: [
    {
      source_id: "source",
      knowledge_base_id: "base",
      display_name: "MES",
      config_revision: 1,
      active_snapshot_id: null,
      collected_revision: null,
      collected_from_revision: null,
      svn_verified: false,
      enabled: 0,
      demand_enabled: 0,
      next_run_at: null,
      plan: {},
      collection: {},
    },
  ],
  source_snapshots: [
    {
      id: "local",
      source_id: "source",
      source_kind: "local_bundle",
      svn_revision: null,
      created_at: "2026-11-06",
      retired_at: null,
    },
  ],
  builds: [
    {
      id: "build",
      source_id: "source",
      source_snapshot_id: "local",
      snapshot_id: "snapshot",
      purpose: "baseline",
      stage: "VALIDATING",
      active: 1,
      error_code: null,
      created_at: "2026-11-06",
      updated_at: "2026-11-06",
      processing_hash: "processing",
      unit_count: 1,
      validated_units: 1,
      validation: {
        machine_valid: true,
        business_verified: false,
        activation_blocked: false,
      },
    },
  ],
  demands: [],
  history_checks: [],
  partial: false,
}
const detail = {
  build_id: "build",
  snapshot_id: "snapshot",
  review_digest: "candidate-digest",
  relations: [],
  units: [
    {
      id: "unit",
      unit_key: "工单发布",
      state: "VALIDATED",
      job_id: "job",
      error_code: null,
      result: {},
    },
  ],
  records: [
    {
      knowledge_id: "publish",
      revision_id: "revision",
      knowledge: {
        title: "发布工单",
        summary: "字段 a 不能为空",
        role: "backend",
        coverage: "analyzed",
        guard: { op: "predicate", expression: "a 非空" },
      },
      evidence: [
        {
          path: "set_server/publish.cpp",
          symbol: "publish",
          start_line: 1,
          end_line: 4,
        },
      ],
    },
  ],
  has_more: false,
  next_cursor: null,
}
function setup(canManage = true, paged = false, remote = false) {
  const responseData = remote
    ? {
        ...data,
        sources: data.sources.map((source) => ({
          ...source,
          svn_verified: true,
          enabled: 1,
          plan: {
            revision: 2,
            application_publication_id: "scheduled-publication",
            service_account_id: "scheduled-service",
            schedule: {
              enabled: false,
              local_time: "02:00",
              timezone: "Asia/Shanghai",
            },
          },
        })),
      }
    : data
  const calls: { path: string; body: unknown }[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const path = String(input)
      if (init.method === "POST") {
        calls.push({ path, body: JSON.parse(String(init.body)) })
        return new Response(JSON.stringify({ build_id: "build" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }
      return new Response(
        JSON.stringify(
          path.includes("/builds/")
            ? {
                ...detail,
                has_more: paged && !path.includes("after=next"),
                next_cursor: paged ? "next" : null,
              }
            : responseData
        ),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    })
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  render(
    <QueryClientProvider client={client}>
      <CodeKnowledgePanel canRead canManage={canManage} />
    </QueryClientProvider>
  )
  return calls
}
afterEach(() => vi.unstubAllGlobals())

describe("代码知识管理", () => {
  it("独立计划保存时间时区和发布身份，精确版本使用同一来源", async () => {
    const calls = setup(true, false, true)
    await screen.findByText(/SVN 来源已核验/)
    fireEvent.click(screen.getByText("MES · SVN 与更新计划"))
    fireEvent.change(screen.getByLabelText("每日执行时间"), {
      target: { value: "03:30" },
    })
    fireEvent.click(screen.getByLabelText("启用每日采集"))
    fireEvent.click(screen.getByRole("button", { name: "保存更新计划" }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toEqual({
      path: "/api/platform/knowledge/code/sources/source/plan",
      body: {
        expected_plan_revision: 2,
        application_publication_id: "scheduled-publication",
        service_account_id: "scheduled-service",
        schedule_enabled: true,
        demand_enabled: false,
        local_time: "03:30",
        timezone: "Asia/Shanghai",
      },
    })
    fireEvent.change(screen.getByLabelText("预构建 SVN 版本"), {
      target: { value: "101" },
    })
    fireEvent.click(screen.getByRole("button", { name: "登记精确版本" }))
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[1]).toEqual({
      path: "/api/platform/knowledge/code/sources/source/versions",
      body: { revision: 101 },
    })
  })
  it("显示本地未知 SVN，构建只提交登记身份", async () => {
    const calls = setup()
    await screen.findByRole("button", { name: "启动基线提取" })
    expect(screen.getByText(/已采集 SVN：未核实/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("已登记源码快照"), {
      target: { value: "local" },
    })
    fireEvent.change(screen.getByLabelText("提取应用发布 ID"), {
      target: { value: "app-publication" },
    })
    fireEvent.change(screen.getByLabelText("执行服务账号 ID"), {
      target: { value: "service-account" },
    })
    fireEvent.click(screen.getByRole("button", { name: "启动基线提取" }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toEqual({
      source_id: "source",
      source_snapshot_id: "local",
      application_publication_id: "app-publication",
      service_account_id: "service-account",
    })
  })
  it("读完分页后才显示核验，绑定候选摘要和单元", async () => {
    const calls = setup(true, true)
    fireEvent.click(
      await screen.findByRole("button", { name: "查看候选与进度" })
    )
    await screen.findByText("发布工单")
    expect(
      screen.queryByRole("button", { name: "记录核验通过并继续构建" })
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "继续阅读下一页" }))
    const submit = await screen.findByRole("button", {
      name: "记录核验通过并继续构建",
    })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText("独立核验记录编号"), {
      target: { value: "review-1" },
    })
    fireEvent.click(screen.getByRole("checkbox", { name: /我已独立核验/ }))
    fireEvent.click(submit)
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toEqual({
      review_reference: "review-1",
      processing_hash: "processing",
      candidate_digest: "candidate-digest",
      checked_unit_ids: ["unit"],
    })
  })
  it("只读管理用户看到进度，没有提取或核验按钮", async () => {
    setup(false)
    await screen.findByText("等待业务核验")
    expect(
      screen.queryByRole("button", { name: "启动基线提取" })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "查看候选与进度" })
    ).not.toBeInTheDocument()
    expect(screen.getByText("已校验单元 1 / 1")).toBeInTheDocument()
  })
})
