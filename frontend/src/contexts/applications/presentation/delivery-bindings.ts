import type { SaveDraftInput } from "@/contexts/applications/domain/business-application"

type Trigger = SaveDraftInput["triggers"][number]
type Delivery = SaveDraftInput["deliveries"][number]

export function triggerReference(trigger: Trigger) {
  return {
    trigger_type: trigger.trigger_type,
    connector_id: trigger.connector_id,
    routing_key: trigger.routing_key.trim().toLowerCase().replace(/\s+/g, " "),
  }
}

export function matchesTrigger(delivery: Delivery, trigger: Trigger) {
  const source = delivery.config.trigger
  const expected = triggerReference(trigger)
  return (
    source?.trigger_type === expected.trigger_type &&
    source.connector_id === expected.connector_id &&
    source.routing_key.trim().toLowerCase().replace(/\s+/g, " ") ===
      expected.routing_key
  )
}

export function replyOriginal(trigger: Trigger): Delivery {
  return {
    delivery_type: "reply_original",
    connector_id: trigger.connector_id,
    enabled: true,
    config: {
      target_reference: "",
      reply_mode: "original",
      target_user_ids: [],
      trigger: triggerReference(trigger),
    },
  }
}

export function prepareDraftDeliveries(
  triggers: Trigger[],
  deliveries: Delivery[]
): Delivery[] {
  return deliveries.flatMap((delivery) => {
    if (delivery.config.trigger) return [delivery]
    const candidates = triggers.filter((trigger) =>
      delivery.delivery_type === "reply_original"
        ? trigger.trigger_type !== "webhook" &&
          trigger.connector_id === delivery.connector_id
        : trigger.trigger_type === "webhook"
    )
    if (
      candidates.length === 0 ||
      (delivery.delivery_type !== "reply_original" && candidates.length !== 1)
    )
      return [delivery]
    return candidates.map((trigger) => ({
      ...delivery,
      config: { ...delivery.config, trigger: triggerReference(trigger) },
    }))
  })
}

export function replaceTrigger(
  form: SaveDraftInput,
  index: number,
  patch: Partial<Trigger>
): SaveDraftInput {
  const previous = form.triggers[index]
  const next = { ...previous, ...patch }
  const bound = form.deliveries.filter((delivery) =>
    matchesTrigger(delivery, previous)
  )
  const remaining = form.deliveries.filter(
    (delivery) => !matchesTrigger(delivery, previous)
  )
  const replacement =
    next.trigger_type !== "webhook"
      ? [replyOriginal(next)]
      : previous.trigger_type !== "webhook"
        ? []
        : bound.map((delivery) => ({
            ...delivery,
            config: { ...delivery.config, trigger: triggerReference(next) },
          }))
  return {
    ...form,
    triggers: form.triggers.map((trigger, i) => (i === index ? next : trigger)),
    deliveries: [...remaining, ...replacement],
  }
}

export function removeTrigger(
  form: SaveDraftInput,
  index: number
): SaveDraftInput {
  return {
    ...form,
    triggers: form.triggers.filter((_, i) => i !== index),
    deliveries: form.deliveries.filter(
      (delivery) => !matchesTrigger(delivery, form.triggers[index])
    ),
  }
}

export function unassignedDeliveries(form: SaveDraftInput) {
  return form.deliveries.filter(
    (delivery) =>
      !form.triggers.some((trigger) => matchesTrigger(delivery, trigger))
  )
}

export function bindingErrors(
  form: SaveDraftInput,
  allowedWebhookConnectors: string[]
): string[] {
  return form.triggers.flatMap((trigger, index) => {
    const label = `触发器 ${index + 1}`
    if (!trigger.connector_id.trim()) return [`${label}：请选择入口渠道。`]
    if (trigger.trigger_type === "webhook") {
      if (!allowedWebhookConnectors.includes(trigger.connector_id))
        return [
          `${label}：所选 Agent 发布版本未绑定此 Webhook，请切换版本或重新选择入口。`,
        ]
      if (!trigger.routing_key.trim() || !trigger.config.webhook_definition_id)
        return [`${label}：Webhook 入口信息不完整，请重新选择入口渠道。`]
    } else if (
      !trigger.routing_key.trim() ||
      /^(bot|conversation):\s*$/.test(trigger.routing_key)
    ) {
      return [`${label}：请填写完整的路由键。`]
    }
    const delivery = form.deliveries.find((item) =>
      matchesTrigger(item, trigger)
    )
    return delivery && !delivery.connector_id.trim()
      ? [`${label}：请选择投递连接器，或改为仅保存结果。`]
      : []
  })
}
