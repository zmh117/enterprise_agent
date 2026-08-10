import { apiRequest, createIdempotencyKey } from "@/shared/api/api-client"

export type ManagedChannel = {
  id: string
  kind: "WEBHOOK" | "DINGTALK_APP_ROBOT"
  name: string
  code?: string
  client_id?: string
  enabled: boolean
  revision: number
  secret_configured?: boolean
  enterprise?: {
    id: string
    name: string
    status: string
    corp_id_verified: boolean
    verified_at?: string | null
  }
  runtime?: {
    status: string
    loaded_revision?: number | null
    last_heartbeat_at?: string | null
    last_message_at?: string | null
    last_error?: string
  }
  references?: Array<{
    application_code: string
    application_name: string
    application_revision: number
    trigger_type: string
  }>
  capabilities?: {
    private_chat: boolean
    group_chat: boolean
    require_group_at?: boolean
  }
}

export type DingTalkEnterprise = {
  id: string
  name: string
  status: string
  revision: number
  connector_count: number
  enabled_connector_count: number
}

export type ChannelCredential = {
  id: string
  code: string
  purpose: string
  status: string
  active_version: number
  masked_summary: string
  revision: number
}

export async function listManagedChannels() {
  const result = await apiRequest<{ items: ManagedChannel[] }>(
    "/api/admin/managed-channels"
  )
  return result.items
}

export async function setManagedChannelEnabled(
  channel: ManagedChannel,
  enabled: boolean
) {
  const action = enabled ? "enable" : "disable"
  return apiRequest<{ channel: ManagedChannel }>(
    `/api/admin/managed-channels/${encodeURIComponent(channel.id)}/${action}`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey(`managed-channel-${action}`),
      },
      body: { expected_revision: channel.revision },
    }
  )
}

export async function restartManagedChannel(channel: ManagedChannel) {
  return apiRequest<{ channel: ManagedChannel }>(
    `/api/admin/managed-channels/${encodeURIComponent(channel.id)}/restart`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey("managed-channel-restart"),
      },
      body: { expected_revision: channel.revision },
    }
  )
}

export async function testManagedChannel(channel: ManagedChannel) {
  return apiRequest<{ result: { status: string; summary: string; tested_at: string } }>(
    `/api/admin/managed-channels/${encodeURIComponent(channel.id)}/test`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey("managed-channel-test"),
      },
      body: {},
    }
  )
}

export async function listDingTalkEnterprises() {
  const result = await apiRequest<{ items: DingTalkEnterprise[] }>(
    "/api/admin/managed-channels/dingtalk-enterprises"
  )
  return result.items
}

export async function createDingTalkEnterprise(name: string) {
  const result = await apiRequest<{ enterprise: DingTalkEnterprise }>(
    "/api/admin/managed-channels/dingtalk-enterprises",
    {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("dingtalk-enterprise") },
      body: { name },
    }
  )
  return result.enterprise
}

export async function listChannelCredentials() {
  const result = await apiRequest<{ items: ChannelCredential[] }>(
    "/api/admin/managed-channels/credential-candidates"
  )
  return result.items
}

export type DingTalkChannelForm = {
  expected_revision: number
  name: string
  client_id: string
  credential_id: string
  dingtalk_enterprise_id: string
  allow_private_chat: boolean
  allow_group_chat: boolean
  require_group_at: boolean
  enabled: boolean
}

export async function saveDingTalkChannel(input: {
  channelId?: string
  form: DingTalkChannelForm
}) {
  const path = input.channelId
    ? `/api/admin/managed-channels/dingtalk-app-robots/${encodeURIComponent(input.channelId)}`
    : "/api/admin/managed-channels/dingtalk-app-robots"
  const result = await apiRequest<{ channel: ManagedChannel }>(path, {
    method: input.channelId ? "PUT" : "POST",
    headers: { "Idempotency-Key": createIdempotencyKey("dingtalk-channel-save") },
    body: input.form,
  })
  return result.channel
}
