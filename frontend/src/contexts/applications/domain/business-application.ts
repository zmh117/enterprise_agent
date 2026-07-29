import { z } from "zod"

export const runtimeComponentSchema = z.object({
  status: z.enum([
    "wired",
    "partially_wired",
    "stored_only",
    "unsupported",
    "blocked",
  ]),
  reason_code: z.string().default(""),
  message: z.string().default(""),
  fields: z.record(z.string(), z.string()).default({}),
  impact: z.enum(["runtime", "governance"]).default("runtime"),
})

export const runtimeStateSchema = z.object({
  runtime_wired: z.boolean().default(false),
  runtime_status: z
    .enum(["not_wired", "partially_wired", "wired", "blocked"])
    .default("not_wired"),
  runtime_environment: z.string().default(""),
  deployment_environment: z.string().default(""),
  reason_code: z.string().default("runtime_state_missing"),
  message: z.string().default("运行时状态尚未返回，按未接管处理。"),
  runtime_components: z.record(z.string(), runtimeComponentSchema).default({}),
  affected_routes: z
    .array(
      z.object({
        trigger_type: z.string(),
        connector_id: z.string(),
        routing_key_summary: z.string(),
      })
    )
    .default([]),
  legacy_fallback_enabled: z.boolean().default(false),
})

const validationErrorSchema = z.object({
  field: z.string(),
  message: z.string(),
})

export const validationSchema = z.object({
  valid: z.boolean().default(false),
  errors: z.array(validationErrorSchema).default([]),
})

const triggerSchema = z
  .object({
    trigger_type: z.string(),
    connector_id: z.string(),
    routing_key: z.string(),
    normalized_routing_key: z.string().optional(),
    actor_policy: z.string(),
    service_account_user_id: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    enabled: z.boolean(),
    config: z.record(z.string(), z.unknown()).default({}),
  })
  .passthrough()

const deliverySchema = z
  .object({
    delivery_type: z.string(),
    connector_id: z.string(),
    enabled: z.boolean(),
    config: z.record(z.string(), z.unknown()).default({}),
  })
  .passthrough()

const capabilitySchema = z
  .object({
    capability_code: z.string(),
    version_constraint: z.string().default(""),
    enabled: z.boolean(),
  })
  .passthrough()

export const revisionSchema = z
  .object({
    id: z.string(),
    application_id: z.string(),
    revision: z.number(),
    status: z.string(),
    agent_publication_id: z.string().default(""),
    workflow_publication_id: z.string().default(""),
    session_policy: z.record(z.string(), z.unknown()).default({}),
    execution_policy: z.record(z.string(), z.unknown()).default({}),
    validation: validationSchema.default({ valid: false, errors: [] }),
    config_hash: z.string().default(""),
    triggers: z.array(triggerSchema).default([]),
    deliveries: z.array(deliverySchema).default([]),
    capabilities: z.array(capabilitySchema).default([]),
    created_at: z.string().default(""),
    updated_at: z.string().default(""),
  })
  .passthrough()

export const publicationSchema = runtimeStateSchema
  .extend({
    id: z.string(),
    application_id: z.string(),
    revision_id: z.string(),
    revision: z.number(),
    schema_version: z.number(),
    config_hash: z.string(),
    published_by: z.string(),
    published_at: z.string(),
    snapshot: z.record(z.string(), z.unknown()).optional(),
  })
  .passthrough()

export const deploymentSchema = runtimeStateSchema
  .extend({
    id: z.string(),
    application_id: z.string(),
    environment: z.string(),
    publication_id: z.string(),
    active: z.boolean(),
    revision: z.number(),
    activated_by: z.string().default(""),
    activated_at: z.string().default(""),
    deactivated_at: z.string().default(""),
  })
  .passthrough()

export const applicationSummarySchema = runtimeStateSchema
  .extend({
    id: z.string(),
    code: z.string(),
    name: z.string(),
    description: z.string(),
    project_code: z.string(),
    owner_user_id: z.string(),
    status: z.enum(["enabled", "disabled", "archived"]),
    revision: z.number(),
    latest_publication_revision: z.number().nullable().optional(),
    active_environments: z.array(z.string()).default([]),
  })
  .passthrough()

export const businessApplicationSchema = applicationSummarySchema.extend({
  draft: revisionSchema.nullable().optional(),
  publications: z.array(publicationSchema).default([]),
  deployments: z.array(deploymentSchema).default([]),
  capability_catalog_connected: z.boolean().default(false),
})

export type ApplicationSummary = z.infer<typeof applicationSummarySchema>
export type BusinessApplication = z.infer<typeof businessApplicationSchema>
export type BusinessApplicationRevision = z.infer<typeof revisionSchema>
export type Publication = z.infer<typeof publicationSchema>
export type Deployment = z.infer<typeof deploymentSchema>
export type RuntimeState = z.infer<typeof runtimeStateSchema>

export type CreateApplicationInput = {
  code: string
  name: string
  description: string
  project_code: string
  owner_user_id: string
}

export type SaveDraftInput = {
  expected_revision: number
  agent_publication_id: string
  workflow_publication_id: string
  session_policy: {
    conversation_mode: "channel"
    recent_message_limit: number
    retention_days: number
  }
  execution_policy: {
    max_turns: number
    timeout_seconds: number
    max_tool_calls: number
  }
  triggers: Array<{
    trigger_type: "dingtalk_private" | "dingtalk_group" | "webhook"
    connector_id: string
    routing_key: string
    actor_policy: "CURRENT_SENDER" | "SERVICE_ACCOUNT"
    service_account_user_id: string
    enabled: boolean
    config: {
      conversation_type: string
      require_mention: boolean
      webhook_definition_id: string
    }
  }>
  deliveries: Array<{
    delivery_type:
      | "reply_original"
      | "dingtalk_private"
      | "dingtalk_group"
      | "webhook_callback"
    connector_id: string
    enabled: boolean
    config: {
      target_reference: string
      reply_mode: string
    }
  }>
  capabilities: Array<{
    capability_code: string
    version_constraint: string
    enabled: boolean
  }>
}
