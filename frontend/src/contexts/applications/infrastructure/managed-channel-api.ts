import { z } from "zod"

import {
  managedChannelSchema,
  type DingTalkChannelInput,
  type WebhookChannelInput,
} from "@/contexts/applications/domain/managed-channel"
import { apiRequest } from "@/shared/api/api-client"

const itemsSchema = z.object({ items: z.array(managedChannelSchema) })
const channelSchema = z.object({ channel: managedChannelSchema })

export async function listManagedChannels() {
  return itemsSchema.parse(
    await apiRequest("/api/admin/managed-channels")
  ).items
}

export async function listEligibleChannels(triggerType: string) {
  return itemsSchema.parse(
    await apiRequest(
      `/api/admin/managed-channels/eligible?trigger_type=${encodeURIComponent(triggerType)}`
    )
  ).items
}

export async function createDingTalkChannel(input: DingTalkChannelInput) {
  return channelSchema.parse(
    await apiRequest("/api/admin/managed-channels/dingtalk-app-robots", {
      method: "POST",
      body: input,
    })
  ).channel
}

export async function updateDingTalkChannel(
  connectorId: string,
  input: DingTalkChannelInput
) {
  return channelSchema.parse(
    await apiRequest(
      `/api/admin/managed-channels/dingtalk-app-robots/${encodeURIComponent(connectorId)}`,
      { method: "PUT", body: input }
    )
  ).channel
}

export async function setManagedChannelEnabled(
  channelId: string,
  revision: number,
  enabled: boolean
) {
  return channelSchema.parse(
    await apiRequest(
      `/api/admin/managed-channels/${encodeURIComponent(channelId)}/${enabled ? "enable" : "disable"}`,
      { method: "POST", body: { expected_revision: revision } }
    )
  ).channel
}

export async function restartManagedChannel(
  channelId: string,
  revision: number
) {
  return channelSchema.parse(
    await apiRequest(
      `/api/admin/managed-channels/${encodeURIComponent(channelId)}/restart`,
      { method: "POST", body: { expected_revision: revision } }
    )
  ).channel
}

export async function deleteManagedChannel(
  channelId: string,
  revision: number
) {
  await apiRequest(
    `/api/admin/managed-channels/${encodeURIComponent(channelId)}?expected_revision=${revision}`,
    { method: "DELETE" }
  )
}

export async function createWebhookChannel(input: WebhookChannelInput) {
  return apiRequest("/api/admin/managed-channels/webhooks", {
    method: "POST",
    body: input,
  })
}
