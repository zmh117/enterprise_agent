import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ManagedChannelsPanel } from "@/contexts/applications/presentation/managed-channels-panel"
import type {
  WebhookConfig,
  WebhookDetail,
} from "@/contexts/applications/domain/webhook"

function setup(enabled = false) {
  let detail: WebhookDetail = {
    definition: {
      id: "trigger-1",
      code: "synthetic-hook",
      name: "合成入口",
      trigger_type: "generic",
      connector_id: "source-1",
      public_id: "wh_synthetic",
      revision: 1,
      status: enabled ? "enabled" : "disabled",
      service_account_id: "service-1",
      service_account_username: "svc-webhook-synthetic-hook",
      service_account_status: "enabled",
    },
    draft: null,
    current_publication: null,
  }
  const writes: Array<{ url: string; body: Record<string, unknown> }> = []
  let created = enabled
  let conflict = false
  const reply = (body: unknown, status = 200) =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      })
    )
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input)
    const method = init?.method ?? "GET"
    const body = JSON.parse(String(init?.body ?? "{}")) as Record<
      string,
      unknown
    >
    if (method !== "GET") writes.push({ url, body })
    if (url.endsWith("/dingtalk-enterprises")) return reply({ items: [] })
    if (url.endsWith("/api/admin/managed-channels"))
      return reply({
        items: created
          ? [
              {
                id: "source-1",
                kind: "WEBHOOK",
                name: "合成入口",
                code: "synthetic-hook",
                webhook_trigger_id: "trigger-1",
                enabled: detail.definition.status === "enabled",
                revision: detail.definition.revision,
              },
            ]
          : [],
      })
    if (url.endsWith("/managed-channels/webhooks")) {
      created = true
      return reply({ webhook: { definition: detail.definition } })
    }
    if (url.endsWith("/webhook-triggers/catalog"))
      return reply({
        agents: [
          {
            code: "synthetic-agent",
            name: "合成 Agent",
            publication_id: "agent-pub-1",
            revision: 2,
          },
        ],
        connectors: [
          {
            id: "robot-1",
            name: "合成机器人",
            connector_type: "dingtalk_enterprise_stream",
            allow_delivery: false,
            supports_robot_delivery: true,
          },
        ],
      })
    if (url.endsWith("/platform/secrets"))
      return reply({
        secrets: [
          {
            id: "secret-1",
            code: "synthetic",
            provider: "platform",
            secret_ref: "secret://platform/synthetic",
            status: "enabled",
            active_version: 1,
            configured: true,
            revision: 1,
          },
        ],
      })
    if (url.endsWith("/webhook-triggers/synthetic-hook") && method === "GET")
      return reply({ trigger: detail })
    if (url.endsWith("/revisions")) {
      if (conflict)
        return reply(
          {
            detail: {
              code: "revision_conflict",
              message: "Webhook 触发器草稿已发生变化，请刷新后重试",
            },
          },
          409
        )
      detail = {
        ...detail,
        draft: {
          id: "draft-1",
          revision: (detail.draft?.revision ?? 0) + 1,
          config: body.config as WebhookConfig,
          validation: {},
        },
      }
      return reply({ revision: detail.draft })
    }
    if (url.endsWith("/validate")) {
      detail = {
        ...detail,
        draft: { ...detail.draft!, validation: { valid: true, errors: [] } },
      }
      return reply({ revision: detail.draft })
    }
    if (url.endsWith("/preview"))
      return reply({
        preview: { message: "合成测试消息", side_effects: false },
      })
    if (url.endsWith("/publish")) {
      detail = {
        ...detail,
        definition: { ...detail.definition, revision: 2 },
        current_publication: { id: "publication-1", revision: 1 },
      }
      return reply({ publication: detail.current_publication })
    }
    if (
      url.endsWith("/webhook-triggers/synthetic-hook") &&
      method === "PATCH"
    ) {
      detail = {
        ...detail,
        definition: {
          ...detail.definition,
          status: body.status as "enabled" | "disabled",
          revision: detail.definition.revision + 1,
        },
      }
      return reply({ definition: detail.definition })
    }
    throw new Error(`Unexpected request ${method} ${url}`)
  })
  render(
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
      <ManagedChannelsPanel />
    </QueryClientProvider>
  )
  return {
    writes,
    conflict: () => {
      conflict = true
    },
  }
}
async function createWebhook() {
  fireEvent.click(await screen.findByRole("button", { name: "新建 Webhook" }))
  expect(screen.queryByLabelText("入口 Connector")).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText("Webhook 编码"), {
    target: { value: "synthetic-hook" },
  })
  fireEvent.change(screen.getByLabelText("Webhook 名称"), {
    target: { value: "合成入口" },
  })
  fireEvent.click(screen.getByRole("button", { name: "创建并配置 Webhook" }))
  await screen.findByLabelText("Bearer 凭据引用")
}
async function fillDraft() {
  fireEvent.change(screen.getByLabelText("Bearer 凭据引用"), {
    target: { value: "secret://platform/synthetic" },
  })
  await screen.findByRole("option", {
    name: "合成 Agent · synthetic-agent · r2",
  })
  fireEvent.change(screen.getByLabelText("Agent 发布版本"), {
    target: { value: "agent-pub-1" },
  })
  fireEvent.change(screen.getByLabelText("项目编码值"), {
    target: { value: "synthetic" },
  })
}

describe("Webhook first-use configuration", () => {
  it("saves and reopens multiple group and user recipients", async () => {
    const { writes } = setup()
    await createWebhook()
    await fillDraft()
    fireEvent.change(screen.getByLabelText("结果投递"), {
      target: { value: "dingtalk_recipients" },
    })
    fireEvent.change(screen.getByLabelText("接收人 1 目标 ID"), {
      target: { value: "synthetic-group" },
    })
    fireEvent.click(screen.getByRole("button", { name: "添加接收人" }))
    fireEvent.change(screen.getByLabelText("接收人 2 类型"), {
      target: { value: "user" },
    })
    fireEvent.change(screen.getByLabelText("接收人 2 目标 ID"), {
      target: { value: "synthetic-user" },
    })
    fireEvent.change(screen.getByLabelText("接收人 2 备注"), {
      target: { value: "合成用户" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }))
    await screen.findByText("草稿已保存，当前运行版本保持不变。")
    const config = writes.find((item) => item.url.endsWith("/revisions"))!.body
      .config as WebhookConfig
    expect(config.delivery).toMatchObject({
      type: "dingtalk_recipients",
      connector_id: "",
      target: {
        recipients: [
          {
            connector_id: "robot-1",
            kind: "group",
            target_id: "synthetic-group",
          },
          {
            connector_id: "robot-1",
            kind: "user",
            target_id: "synthetic-user",
            label: "合成用户",
          },
        ],
      },
    })
    fireEvent.click(screen.getByRole("button", { name: "关闭" }))
    fireEvent.click(await screen.findByRole("button", { name: "配置 Webhook" }))
    expect(await screen.findByLabelText("接收人 2 目标 ID")).toHaveValue(
      "synthetic-user"
    )
    fireEvent.click(screen.getByRole("button", { name: "删除接收人 1" }))
    expect(screen.getByLabelText("接收人 1 目标 ID")).toHaveValue(
      "synthetic-user"
    )
  })
  it("stops directly from the channel card", async () => {
    const { writes } = setup(true)
    fireEvent.click(await screen.findByRole("button", { name: "停用 Webhook" }))
    await waitFor(() => expect(writes.at(-1)?.body.status).toBe("disabled"))
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "停用 Webhook" })
      ).not.toBeInTheDocument()
    )
  })
  it("creates without existing connectors, configures, previews, publishes and enables", async () => {
    const { writes } = setup()
    await createWebhook()
    expect(writes[0].body).toEqual({
      code: "synthetic-hook",
      name: "合成入口",
      trigger_type: "generic",
    })
    expect(screen.getByRole("button", { name: "启用 Webhook" })).toBeDisabled()
    await fillDraft()
    expect(screen.getByRole("button", { name: "校验草稿" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }))
    await screen.findByText("草稿已保存，当前运行版本保持不变。")
    const save = writes.find((item) => item.url.endsWith("/revisions"))!
    expect(save.body.expected_revision).toBe(0)
    expect((save.body.config as WebhookConfig).delivery).toEqual({
      type: "none",
      connector_id: "",
      target: {},
      options: {},
    })
    expect(screen.getByRole("button", { name: "发布草稿" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "校验草稿" }))
    await screen.findByText("校验通过，可以预览或发布。")
    fireEvent.click(screen.getByRole("button", { name: "预览映射" }))
    expect(await screen.findByLabelText("映射预览")).toHaveTextContent(
      '"side_effects": false'
    )
    fireEvent.change(screen.getByLabelText("消息模板"), {
      target: { value: "修改 {message}" },
    })
    expect(screen.getByRole("button", { name: "发布草稿" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "预览映射" })).toBeDisabled()
    fireEvent.change(screen.getByLabelText("消息模板"), {
      target: { value: "{message}" },
    })
    fireEvent.click(screen.getByRole("button", { name: "发布草稿" }))
    await screen.findByText(/发布成功；启用后/)
    fireEvent.click(screen.getByRole("button", { name: "启用 Webhook" }))
    await screen.findByRole("button", { name: "停用 Webhook" })
    expect(writes.at(-1)?.body).toMatchObject({
      expected_revision: 2,
      status: "enabled",
      connector_id: "source-1",
    })
    expect(writes.some((item) => item.url.endsWith("/source-1/test"))).toBe(
      false
    )
    fireEvent.change(screen.getByLabelText("消息模板"), {
      target: { value: "未保存 {message}" },
    })
    fireEvent.click(screen.getByRole("button", { name: "停用 Webhook" }))
    await waitFor(() => expect(writes.at(-1)?.body.status).toBe("disabled"))
    expect(screen.getByLabelText("消息模板")).toHaveValue("未保存 {message}")
  })
  it("preserves unsaved input on revision conflicts and rejects malformed mapping JSON locally", async () => {
    const { writes, conflict } = setup()
    await createWebhook()
    await fillDraft()
    fireEvent.change(screen.getByLabelText("变量映射（JSON Pointer）"), {
      target: { value: "invalid-json" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }))
    await screen.findByText("变量映射必须是合法 JSON")
    expect(
      writes.filter((item) => item.url.endsWith("/revisions"))
    ).toHaveLength(0)
    fireEvent.change(screen.getByLabelText("变量映射（JSON Pointer）"), {
      target: { value: '{"message":"/message"}' },
    })
    conflict()
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }))
    await screen.findByText("Webhook 触发器草稿已发生变化，请刷新后重试")
    expect(screen.getByLabelText("项目编码值")).toHaveValue("synthetic")
    expect(screen.getByRole("button", { name: "发布草稿" })).toBeDisabled()
  })
})
