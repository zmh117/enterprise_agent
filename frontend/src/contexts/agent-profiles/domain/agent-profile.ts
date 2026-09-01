import { z } from "zod"

import { mcpServerCodeSchema } from "@/shared/domain/mcp-server-code"

const credentialSchema = z.object({
  configured: z.boolean(),
  masked: z.string(),
  version: z.number(),
  updated_at: z.string(),
  rotation_required: z.boolean(),
})

export const modelConnectionConfigSchema = z.object({
  schema_version: z.number(),
  protocol: z.literal("anthropic_compatible"),
  base_url: z.string(),
  model: z.string(),
  default_opus_model: z.string(),
  default_sonnet_model: z.string(),
  default_haiku_model: z.string(),
  subagent_model: z.string(),
  effort_level: z.enum(["low", "medium", "high", "max"]),
})

export const modelConnectionRevisionSchema = z.object({
  id: z.string(),
  connection_id: z.string(),
  connection_code: z.string(),
  revision: z.number(),
  status: z.string(),
  config: modelConnectionConfigSchema,
  config_hash: z.string(),
  provider_host: z.string(),
  credential: credentialSchema,
  created_by: z.string(),
  created_at: z.string(),
})

export const modelConnectionSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  protocol: z.string(),
  status: z.string(),
  revision: z.number(),
  current_revision_id: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  current_revision: modelConnectionRevisionSchema.nullable(),
  revisions: z.array(modelConnectionRevisionSchema),
})

export const credentialSourceSchema = z.enum(["submitted", "existing"])

export const modelOptionSchema = z.object({
  id: z.string(),
  display_name: z.string(),
})

export const modelDiscoveryResultSchema = z.object({
  provider_host: z.string(),
  normalized_base_url: z.string(),
  models: z.array(modelOptionSchema),
  duration_ms: z.number(),
  credential_source: credentialSourceSchema,
})

export const modelDraftTestResultSchema = z.object({
  success: z.boolean(),
  provider_host: z.string(),
  model: z.string(),
  duration_ms: z.number(),
  runtime: z.string(),
  detail: z.string(),
})

export const runtimeKindSchema = z.literal("python-v1")

export const agentDefinitionSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  description: z.string(),
  project_code: z.string(),
  status: z.string(),
  revision: z.number(),
  runtime_kind: runtimeKindSchema.default("python-v1"),
  current_publication_id: z.string().nullable(),
  classification: z.string().optional(),
})

export const modelSavedTestResultSchema = z.object({
  success: z.boolean(),
  connection_revision_id: z.string(),
  provider_host: z.string(),
  model: z.string(),
  duration_ms: z.number(),
  runtime: z.literal("python-v1"),
  runtime_version: z.string(),
  sdk_version: z.string(),
})

const modelPolicySchema = z
  .object({
    runtime: z.string().optional(),
    model: z.string(),
    model_connection_revision_id: z.string().optional(),
  })
  .passthrough()

export const agentConfigSchema = z.object({
  business_role: z.string(),
  business_instructions: z.string(),
  model_policy: modelPolicySchema,
  execution: z.object({
    max_turns: z.number(),
    timeout_seconds: z.number(),
  }),
  skills: z.array(z.string()),
  routing: z.object({ project_code: z.string() }),
  channels: z.object({
    ingress: z.array(z.string()),
    delivery: z.array(z.string()),
  }),
  mcp_tool_ids: z.array(z.string()).default([]),
})

export const agentRevisionSchema = z.object({
  id: z.string(),
  revision: z.number(),
  status: z.string(),
  config_hash: z.string(),
  config: agentConfigSchema,
  validation: z
    .object({
      valid: z.boolean().optional(),
      errors: z
        .array(z.object({ field: z.string(), message: z.string() }))
        .optional(),
    })
    .passthrough(),
  created_at: z.string(),
  updated_at: z.string(),
})

export const activeApplicationSchema = z.object({
  code: z.string(),
  name: z.string(),
  environment: z.string(),
  application_publication_id: z.string(),
  href: z.string(),
})

export const agentPublicationSchema = z.object({
  id: z.string(),
  revision: z.number(),
  config_hash: z.string(),
  runtime_kind: z.literal("python-v1").default("python-v1"),
  snapshot: agentConfigSchema.passthrough(),
  published_at: z.string(),
  published_by: z.string(),
  active_applications: z.array(activeApplicationSchema).optional(),
  model_runtime_mode: z.string().optional(),
  runtime_protocol_compatibility: z
    .enum(["current", "historical_read_only"])
    .optional(),
  execution_compatibility: z
    .enum(["current", "historical_read_only"])
    .optional(),
  incompatibility_reasons: z
    .array(z.enum(["runtime_protocol", "mcp_tool_policy"]))
    .default([]),
})

export const agentDetailSchema = z.object({
  definition: agentDefinitionSchema,
  draft: agentRevisionSchema.nullable(),
  current_publication: agentPublicationSchema.nullable(),
  management_mode: z.literal("editable").default("editable"),
  permissions: z
    .object({
      can_edit_profile: z.boolean(),
      can_publish: z.boolean(),
      can_manage_credential: z.boolean(),
      can_test_connection: z.boolean(),
    })
    .default({
      can_edit_profile: false,
      can_publish: false,
      can_manage_credential: false,
      can_test_connection: false,
    }),
  catalog: z.object({
    models: z.array(z.string()),
    skills: z.array(z.string()),
    connectors: z.array(
      z.object({
        id: z.string(),
        connector_type: z.string(),
        name: z.string(),
        enabled: z.union([z.boolean(), z.number()]),
        allow_ingress: z.union([z.boolean(), z.number()]),
        allow_delivery: z.union([z.boolean(), z.number()]),
      })
    ),
    mcp_tools: z
      .array(
        z.object({
          server_code: mcpServerCodeSchema,
          identifier: z.string(),
          description: z.string(),
          schema_hash: z.string(),
          resource_kind: z.string(),
          read_only: z.boolean(),
          effect: z.enum(["read", "mutation"]).default("read"),
          confirmation_policy: z.string().default("none"),
        })
      )
      .default([]),
  }),
})

export const agentSummarySchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  description: z.string(),
  project_code: z.string(),
  status: z.string(),
  revision: z.number(),
  runtime_kind: z.literal("python-v1").default("python-v1"),
  management_mode: z.literal("editable").default("editable"),
  current_publication: z
    .object({
      id: z.string(),
      revision: z.number(),
      config_hash: z.string(),
    })
    .nullable(),
  model_connection_status: z.string(),
  active_application_count: z.number(),
})

export const agentListResponseSchema = z.object({
  agents: z.array(agentSummarySchema),
  permissions: z
    .object({ can_create: z.boolean() })
    .default({ can_create: false }),
})

export const agentCreationResultSchema = z.object({
  definition: agentDefinitionSchema,
  draft: agentRevisionSchema,
})

export type AgentConfig = z.infer<typeof agentConfigSchema>
export type AgentDetail = z.infer<typeof agentDetailSchema>
export type ModelConnection = z.infer<typeof modelConnectionSchema>
export type ModelConnectionConfig = z.infer<typeof modelConnectionConfigSchema>
export type CredentialSource = z.infer<typeof credentialSourceSchema>
export type ModelDiscoveryResult = z.infer<typeof modelDiscoveryResultSchema>
export type ModelDraftTestResult = z.infer<typeof modelDraftTestResultSchema>
export type ModelSavedTestResult = z.infer<typeof modelSavedTestResultSchema>
export type RuntimeKind = z.infer<typeof runtimeKindSchema>
export type AgentCreationResult = z.infer<typeof agentCreationResultSchema>
export type AgentCreateInput = {
  code: string
  name: string
  description: string
  project_code: string
}
