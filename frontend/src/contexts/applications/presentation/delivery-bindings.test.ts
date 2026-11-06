import { describe, expect, it } from "vitest"
import type { SaveDraftInput } from "@/contexts/applications/domain/business-application"
import {
  bindingErrors,
  matchesTrigger,
  prepareDraftDeliveries,
  removeTrigger,
  replaceTrigger,
  triggerReference,
  unassignedDeliveries,
} from "./delivery-bindings"

type Trigger = SaveDraftInput["triggers"][number]
const hook = (key: string): Trigger => ({
  trigger_type: "webhook",
  connector_id: key,
  routing_key: `webhook:${key}`,
  actor_policy: "SERVICE_ACCOUNT",
  service_account_user_id: "",
  enabled: true,
  config: {
    conversation_type: "webhook",
    require_mention: false,
    webhook_definition_id: key,
  },
})
const delivery = (
  trigger: Trigger,
  user: string
): SaveDraftInput["deliveries"][number] => ({
  delivery_type: "dingtalk_private",
  connector_id: "robot",
  enabled: true,
  config: {
    trigger: triggerReference(trigger),
    target_reference: "",
    reply_mode: "configured",
    target_user_ids: [user],
  },
})
const form = (
  triggers: Trigger[],
  deliveries: SaveDraftInput["deliveries"]
): SaveDraftInput => ({
  expected_revision: 1,
  agent_publication_id: "agent",
  workflow_publication_id: "",
  task_workspace_retention_period: "WEEK",
  document_processing_profile_code: "NONE",
  task_file_features: {
    workspace_enabled: false,
    file_mcp_enabled: false,
    runtime_file_edit_enabled: false,
    default_file_delivery_enabled: false,
  },
  session_policy: {
    conversation_mode: "channel",
    recent_message_limit: 20,
    retention_days: 30,
    continuous_conversation_enabled: false,
    attachments_enabled: false,
  },
  execution_policy: { max_turns: 12, timeout_seconds: 300, max_tool_calls: 30 },
  triggers,
  deliveries,
  mcp_tools: [],
})

describe("trigger-owned delivery", () => {
  it("reports an unfinished third trigger once without submitting its empty delivery reference", () => {
    const first = hook("first"),
      second = hook("second"),
      unfinished = hook("")
    unfinished.routing_key = ""
    const draft = form(
      [first, second, unfinished],
      [delivery(unfinished, "person-one")]
    )
    expect(bindingErrors(draft, ["first", "second"])).toEqual([
      "触发器 3：请选择入口渠道。",
    ])
  })
  it("requires a bound Agent version and complete source before accepting the delivery", () => {
    const source = hook("first")
    const draft = form([source], [delivery(source, "person-one")])
    expect(bindingErrors(draft, [])).toEqual([
      "触发器 1：所选 Agent 发布版本未绑定此 Webhook，请切换版本或重新选择入口。",
    ])
    expect(bindingErrors(draft, ["first"])).toEqual([])
    draft.deliveries[0].connector_id = ""
    expect(bindingErrors(draft, ["first"])).toEqual([
      "触发器 1：请选择投递连接器，或改为仅保存结果。",
    ])
    source.routing_key = ""
    expect(bindingErrors(draft, ["first"])).toEqual([
      "触发器 1：Webhook 入口信息不完整，请重新选择入口渠道。",
    ])
  })
  it("preserves the other recipient when an earlier trigger is removed or renamed", () => {
    const first = hook("first"),
      second = hook("second")
    const original = form(
      [first, second],
      [delivery(second, "person-two"), delivery(first, "person-one")]
    )
    const changed = replaceTrigger(original, 0, {
      connector_id: "new",
      routing_key: "webhook:new",
    })
    expect(
      changed.deliveries.find((item) =>
        matchesTrigger(item, changed.triggers[0])
      )?.config.target_user_ids
    ).toEqual(["person-one"])
    const removed = removeTrigger(changed, 0)
    expect(removed.triggers).toEqual([second])
    expect(removed.deliveries).toEqual([delivery(second, "person-two")])
  })
  it("resets incompatible delivery when the source type changes", () => {
    const first = hook("first")
    const changed = replaceTrigger(
      form([first], [delivery(first, "person-one")]),
      0,
      {
        trigger_type: "dingtalk_private",
        connector_id: "robot",
        routing_key: "bot:robot",
      }
    )
    expect(changed.deliveries).toMatchObject([
      {
        delivery_type: "reply_original",
        connector_id: "robot",
        config: {
          target_user_ids: [],
          trigger: { trigger_type: "dingtalk_private" },
        },
      },
    ])
    expect(
      replaceTrigger(changed, 0, { trigger_type: "webhook" }).deliveries
    ).toEqual([])
  })
  it("keeps ambiguous or unused legacy recipients visible instead of choosing an entry", () => {
    const first = hook("first"),
      second = hook("second")
    const legacy = delivery(first, "person-one")
    delete legacy.config.trigger
    const ambiguous = form(
      [first, second],
      prepareDraftDeliveries([first, second], [legacy])
    )
    expect(unassignedDeliveries(ambiguous)).toEqual([legacy])
    expect(prepareDraftDeliveries([first], [legacy])[0].config.trigger).toEqual(
      triggerReference(first)
    )
  })
})
