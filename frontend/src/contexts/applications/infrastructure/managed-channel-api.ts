import { z } from "zod"

import {
  dingtalkEnterpriseSchema,
  managedChannelSchema,
  managedChannelTestResultSchema,
  webhookConnectorOptionSchema,
  type DingTalkChannelInput,
  type WebhookChannelInput,
} from "@/contexts/applications/domain/managed-channel"
import { apiRequest } from "@/shared/api/api-client"

const itemsSchema = z.object({ items: z.array(managedChannelSchema) })
const webhookConnectorOptionsSchema = z.object({
  items: z.array(webhookConnectorOptionSchema),
})
const channelSchema = z.object({ channel: managedChannelSchema })
const testResultSchema = z.object({ result: managedChannelTestResultSchema })
const enterprisesSchema = z.object({ items: z.array(dingtalkEnterpriseSchema) })
const enterpriseSchema = z.object({ enterprise: dingtalkEnterpriseSchema })

export async function listManagedChannels() {
  return itemsSchema.parse(await apiRequest("/api/admin/managed-channels"))
    .items
}

export async function listDingTalkEnterprises() {
  return enterprisesSchema.parse(
    await apiRequest("/api/admin/managed-channels/dingtalk-enterprises")
  ).items
}

export async function getDingTalkEnterprise(enterpriseId: string) {
  return enterpriseSchema.parse(
    await apiRequest(
      `/api/admin/managed-channels/dingtalk-enterprises/${encodeURIComponent(enterpriseId)}`
    )
  ).enterprise
}

export async function createDingTalkEnterprise(name: string) {
  return enterpriseSchema.parse(
    await apiRequest("/api/admin/managed-channels/dingtalk-enterprises", {
      method: "POST",
      body: { name },
    })
  ).enterprise
}

export async function renameDingTalkEnterprise(
  enterpriseId: string,
  name: string,
  expectedRevision: number
) {
  return enterpriseSchema.parse(
    await apiRequest(
      `/api/admin/managed-channels/dingtalk-enterprises/${encodeURIComponent(enterpriseId)}`,
      {
        method: "PATCH",
        body: { name, expected_revision: expectedRevision },
      }
    )
  ).enterprise
}

export async function governDingTalkEnterprise(
  enterpriseId: string,
  action: "disable" | "archive" | "restore",
  expectedRevision: number
) {
  return enterpriseSchema.parse(
    await apiRequest(
      `/api/admin/managed-channels/dingtalk-enterprises/${encodeURIComponent(enterpriseId)}/${action}`,
      { method: "POST", body: { expected_revision: expectedRevision } }
    )
  ).enterprise
}

export async function listEligibleChannels(triggerType: string) {
  return itemsSchema.parse(
    await apiRequest(
      `/api/admin/managed-channels/eligible?trigger_type=${encodeURIComponent(triggerType)}`
    )
  ).items
}

export async function listWebhookConnectorOptions() {
  return webhookConnectorOptionsSchema.parse(
    await apiRequest("/api/admin/managed-channels/webhook-connector-options")
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

export async function testManagedChannel(channelId: string) {
  return testResultSchema.parse(
    await apiRequest(
      `/api/admin/managed-channels/${encodeURIComponent(channelId)}/test`,
      { method: "POST", body: {} }
    )
  ).result
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
