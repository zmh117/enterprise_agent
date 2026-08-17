import { z } from "zod"

const secretSchema = z
  .object({
    id: z.string(),
    code: z.string(),
    provider: z.string(),
    secret_ref: z.string().startsWith("secret://platform/"),
    purpose: z.string().default(""),
    status: z.string(),
    active_version: z.number().int().nonnegative(),
    configured: z.boolean(),
    masked_summary: z.string().default(""),
    revision: z.number().int().nonnegative(),
    updated_at: z.string().nullish(),
  })
  .passthrough()

const resourceDraftSchema = z
  .object({
    id: z.string(),
    resource_id: z.string(),
    draft_revision: z.number().int().positive(),
    provider_type: z.string(),
    config: z.record(z.string(), z.unknown()),
    secret_refs: z.record(z.string(), z.string()),
    scope_bindings: z
      .array(z.record(z.string(), z.unknown()))
      .default([]),
    status: z.enum(["DRAFT", "VERIFIED"]),
    updated_at: z.string(),
  })
  .passthrough()

const resourceRevisionSchema = z
  .object({
    id: z.string(),
    resource_id: z.string(),
    revision: z.number().int().positive(),
    provider_type: z.string(),
    provider_contract_version: z.string(),
    config: z.record(z.string(), z.unknown()),
    secret_refs: z.record(z.string(), z.string()),
    scope_bindings: z
      .array(z.record(z.string(), z.unknown()))
      .default([]),
    status: z.enum(["PUBLISHED", "DISABLED", "ARCHIVED"]),
    published_at: z.string(),
  })
  .passthrough()

const resourceVerificationSchema = z
  .object({
    id: z.string(),
    status: z.enum(["PASSED", "FAILED", "BLOCKED"]),
    checks: z.record(z.string(), z.unknown()).default({}),
    safe_error_summary: z.string().default(""),
  })
  .passthrough()

const governedResourceSchema = z
  .object({
    id: z.string(),
    code: z.string(),
    name: z.string(),
    resource_kind: z.enum(["database", "redis", "loki"]),
    scope_type: z.enum(["global", "environment", "base", "workshop"]),
    environment_code: z.string(),
    base_code: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    workshop_code: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    placement: z
      .enum(["cloud", "edge"])
      .nullish()
      .transform((value) => value ?? ""),
    status: z.enum(["enabled", "disabled", "archived"]),
    revision: z.number().int().positive(),
    draft: resourceDraftSchema.nullable(),
    draft_verification: resourceVerificationSchema.nullable().default(null),
    published_revision: resourceRevisionSchema.nullable(),
  })
  .passthrough()

const topologyItemSchema = z
  .object({
    id: z.string(),
    code: z.string(),
    display_name: z.string().default(""),
    status: z.string(),
    environment_code: z.string().optional(),
    base_code: z.string().optional(),
  })
  .passthrough()

const secretDependencySchema = z
  .object({
    dependency_type: z.string(),
    id: z.string(),
    code: z.string(),
    status: z.string(),
    active: z.boolean(),
    field_paths: z.array(z.string()),
    metadata: z.record(z.string(), z.unknown()).default({}),
  })
  .passthrough()

export const secretListResponseSchema = z.object({
  secrets: z.array(secretSchema),
})
export const secretResponseSchema = z.object({ secret: secretSchema })
export const secretUsageResponseSchema = z.object({
  usage: z
    .object({
      secret: secretSchema,
      usage_count: z.number().int().nonnegative(),
      active_usage_count: z.number().int().nonnegative(),
      dependencies: z.array(secretDependencySchema),
    })
    .passthrough(),
})
export const resourceListResponseSchema = z.object({
  resources: z.array(governedResourceSchema),
})
export const resourceCreateResponseSchema = z.object({
  resource: z.record(z.string(), z.unknown()),
  draft: resourceDraftSchema,
})
export const resourceIdentityResponseSchema = z.object({
  resource: z
    .object({
      id: z.string(),
      code: z.string(),
      status: z.enum(["enabled", "disabled", "archived"]),
      revision: z.number().int().positive(),
    })
    .passthrough(),
})
export const resourceDraftResponseSchema = z.object({
  draft: resourceDraftSchema,
})
export const resourceRevisionResponseSchema = z.object({
  revision: resourceRevisionSchema,
})
export const verificationResponseSchema = z.object({
  verification: resourceVerificationSchema,
})
export const environmentResponseSchema = z.object({
  environments: z.array(topologyItemSchema),
})
export const baseResponseSchema = z.object({
  bases: z.array(topologyItemSchema),
})
export const workshopResponseSchema = z.object({
  workshops: z.array(topologyItemSchema),
})
export const lokiDraftTestResponseSchema = z.object({
  test_session_id: z.string(),
  draft_revision: z.number().int().positive(),
  labels: z.array(z.string()),
  label_count: z.number().int().nonnegative(),
  truncated: z.boolean(),
  expires_at: z.string(),
})
export const lokiLabelValuesResponseSchema = z.object({
  label: z.string(),
  values: z.array(z.string()),
  value_count: z.number().int().nonnegative(),
  truncated: z.boolean(),
})

export type PlatformSecret = z.infer<typeof secretSchema>
export type GovernedResource = z.infer<typeof governedResourceSchema>
export type ResourceDraft = z.infer<typeof resourceDraftSchema>
export type ResourceRevision = z.infer<typeof resourceRevisionSchema>
export type ResourceVerification = z.infer<typeof resourceVerificationSchema>
export type TopologyItem = z.infer<typeof topologyItemSchema>

export type ResourceFormInput = {
  code: string
  name: string
  resource_kind: "database" | "redis" | "loki"
  scope_type: "global" | "environment" | "base" | "workshop"
  environment_code: string
  base_code: string
  workshop_code: string
  placement?: "cloud" | "edge" | ""
  provider_type: "mysql" | "sqlserver" | "oracle" | "redis" | "loki"
  config: Record<string, unknown>
  secret_refs: Record<string, string>
  scope_bindings: Array<Record<string, unknown>>
  create_environment_if_missing?: boolean
}
