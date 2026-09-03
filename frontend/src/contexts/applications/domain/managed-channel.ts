import { z } from "zod"

const runtimeSummarySchema = z.object({
  status: z.string().default("STOPPED"),
  loaded_revision: z.number().nullable().optional(),
  last_heartbeat_at: z.string().nullable().optional(),
  last_message_at: z.string().nullable().optional(),
  last_error: z.string().default(""),
})

export const dingtalkEnterpriseStatusSchema = z.enum([
  "PENDING_VERIFICATION",
  "ACTIVE",
  "DISABLED",
  "ARCHIVED",
])

const dingtalkEnterpriseSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  status: z.union([dingtalkEnterpriseStatusSchema, z.literal("UNASSIGNED")]),
  corp_id_verified: z.boolean(),
  verified_at: z.string().nullable().optional(),
})

const dingtalkEnterpriseImpactSchema = z.object({
  connector_id: z.string(),
  connector_name: z.string(),
  connector_enabled: z.boolean(),
  application_id: z.string(),
  application_name: z.string(),
  application_revision: z.number().int().nullable().optional(),
})

const managedChannelReferenceSchema = z.object({
  application_code: z.string(),
  application_name: z.string(),
  application_revision: z.number().int().nonnegative(),
  trigger_type: z.string(),
})

export const dingtalkEnterpriseSchema = z.object({
  id: z.string(),
  name: z.string(),
  corp_id: z.string(),
  status: dingtalkEnterpriseStatusSchema,
  verified_at: z.string().nullable().optional(),
  revision: z.number().int().positive(),
  connector_count: z.number().int().nonnegative(),
  enabled_connector_count: z.number().int().nonnegative(),
  created_at: z.string(),
  updated_at: z.string(),
  impacts: z.array(dingtalkEnterpriseImpactSchema).optional(),
})

export type DingTalkEnterprise = z.infer<typeof dingtalkEnterpriseSchema>

export const managedChannelSchema = z
  .object({
    id: z.string(),
    kind: z.enum(["WEBHOOK", "DINGTALK_APP_ROBOT"]),
    name: z.string(),
    code: z.string().optional(),
    client_id: z.string().optional(),
    enterprise: dingtalkEnterpriseSummarySchema.optional(),
    webhook_trigger_id: z.string().optional(),
    routing_key: z.string().optional(),
    enabled: z.boolean(),
    revision: z.number(),
    secret_configured: z.boolean().optional(),
    work_notification_agent_id_configured: z.boolean().default(false),
    work_notification_agent_id_hint: z.string().default(""),
    enterprise_robot_code: z.string().default(""),
    external_action_confirmation_card_template_id: z.string().default(""),
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
    references: z.array(managedChannelReferenceSchema).default([]),
    runtime: runtimeSummarySchema.optional(),
    updated_at: z.string().nullable().optional(),
  })
  .passthrough()

export type ManagedChannel = z.infer<typeof managedChannelSchema>

export const webhookConnectorOptionSchema = z.object({
  id: z.string(),
  name: z.string(),
  connector_type: z.string(),
  revision: z.number(),
})

export type WebhookConnectorOption = z.infer<
  typeof webhookConnectorOptionSchema
>

export const managedChannelTestResultSchema = z.object({
  status: z.literal("READY"),
  summary: z.string(),
  tested_at: z.string(),
})

export type ManagedChannelTestResult = z.infer<
  typeof managedChannelTestResultSchema
>

export type DingTalkChannelInput = {
  expected_revision: number
  name: string
  client_id: string
  client_secret: string
  dingtalk_enterprise_id: string
  allow_private_chat: boolean
  allow_group_chat: boolean
  require_group_at: boolean
  work_notification_agent_id: number | null
  enterprise_robot_code: string
  external_action_confirmation_card_template_id: string
  enabled: boolean
  rotate_secret: boolean
}

export type WebhookChannelInput = {
  code: string
  name: string
  trigger_type: "generic" | "grafana"
  connector_id: string
}
