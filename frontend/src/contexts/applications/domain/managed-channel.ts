import { z } from "zod"

const runtimeSummarySchema = z.object({
  status: z.string().default("STOPPED"),
  loaded_revision: z.number().nullable().optional(),
  last_heartbeat_at: z.string().nullable().optional(),
  last_message_at: z.string().nullable().optional(),
  last_error: z.string().default(""),
})

export const managedChannelSchema = z
  .object({
    id: z.string(),
    kind: z.enum(["WEBHOOK", "DINGTALK_APP_ROBOT"]),
    name: z.string(),
    code: z.string().optional(),
    client_id: z.string().optional(),
    tenant_code: z.string().optional(),
    webhook_trigger_id: z.string().optional(),
    routing_key: z.string().optional(),
    enabled: z.boolean(),
    revision: z.number(),
    secret_configured: z.boolean().optional(),
    capabilities: z
      .object({
        private_chat: z.boolean().default(false),
        group_chat: z.boolean().default(false),
        require_group_at: z.boolean().default(false),
      })
      .default({
        private_chat: false,
        group_chat: false,
        require_group_at: false,
      }),
    runtime: runtimeSummarySchema.optional(),
    updated_at: z.string().nullable().optional(),
  })
  .passthrough()

export type ManagedChannel = z.infer<typeof managedChannelSchema>

export type DingTalkChannelInput = {
  expected_revision: number
  name: string
  client_id: string
  client_secret: string
  tenant_code: string
  allow_private_chat: boolean
  allow_group_chat: boolean
  require_group_at: boolean
  enabled: boolean
  rotate_secret: boolean
}

export type WebhookChannelInput = {
  code: string
  name: string
  trigger_type: "generic" | "grafana"
  connector_id: string
}
