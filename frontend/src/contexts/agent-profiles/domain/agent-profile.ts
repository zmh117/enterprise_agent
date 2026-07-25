import { z } from "zod"

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
  tools: z.array(z.string()),
  skills: z.array(z.string()),
  routing: z.object({ project_code: z.string() }),
  channels: z.object({
    ingress: z.array(z.string()),
    delivery: z.array(z.string()),
  }),
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
  snapshot: agentConfigSchema.passthrough(),
  published_at: z.string(),
  published_by: z.string(),
  active_applications: z.array(activeApplicationSchema).optional(),
  model_runtime_mode: z.string().optional(),
})

export const agentDetailSchema = z.object({
  definition: z.object({
    id: z.string(),
    code: z.string(),
    name: z.string(),
    description: z.string(),
    project_code: z.string(),
    status: z.string(),
    revision: z.number(),
    current_publication_id: z.string().nullable(),
  }),
  draft: agentRevisionSchema.nullable(),
  current_publication: agentPublicationSchema.nullable(),
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
    tools: z.array(z.string()),
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
  management_mode: z.enum(["editable", "read_only"]),
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

export type AgentConfig = z.infer<typeof agentConfigSchema>
export type AgentDetail = z.infer<typeof agentDetailSchema>
export type ModelConnection = z.infer<typeof modelConnectionSchema>
export type ModelConnectionConfig = z.infer<typeof modelConnectionConfigSchema>
