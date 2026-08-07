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

const affectedApplicationSchema = z
  .object({
    publication_id: z.string(),
    application_id: z.string(),
    application_code: z.string(),
    application_name: z.string(),
    runtime_status: z.string(),
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
    status: z.enum(["enabled", "disabled", "archived"]),
    revision: z.number().int().positive(),
    draft: resourceDraftSchema.nullable(),
    draft_verification: resourceVerificationSchema.nullable().default(null),
    published_revision: resourceRevisionSchema.nullable(),
    effective_revision_id: z.string().default(""),
    activation_status: z.string().default("EMPTY"),
    last_known_good_generation_id: z.string().default(""),
    safe_error_summary: z.string().default(""),
    affected_applications: z.array(affectedApplicationSchema).default([]),
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

const runtimeStatusSchema = z
  .object({
    status: z.string(),
    observed_published_generation: z
      .object({
        id: z.string(),
        number: z.number(),
        digest: z.string(),
      })
      .nullable(),
    effective_generation: z
      .object({
        id: z.string(),
        number: z.number(),
        digest: z.string(),
      })
      .nullable(),
    resources: z.array(z.record(z.string(), z.unknown())).default([]),
    applications: z.array(z.record(z.string(), z.unknown())).default([]),
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

const builtinToolResourceSlotSchema = z
  .object({
    code: z.string(),
    resource_kind: z.enum(["database", "redis", "loki"]),
    required: z.boolean(),
    allowed_scope_types: z.array(z.enum(["environment", "base", "workshop"])),
  })
  .passthrough()

const builtinToolManifestSchema = z
  .object({
    tool_identifier: z.string(),
    tool_semantic_version: z.string(),
    handler_id: z.string(),
    handler_version: z.string(),
    display_name: z.string(),
    description: z.string(),
    input_schema: z.record(z.string(), z.unknown()),
    output_schema: z.record(z.string(), z.unknown()),
    risk_level: z.enum(["LOW", "MEDIUM", "HIGH"]),
    required_permissions: z.array(z.string()),
    resource_slots: z.array(builtinToolResourceSlotSchema),
    visibility: z.enum(["application", "internal_diagnostic"]),
    public_schema_hash: z.string(),
    verifier_plan: z
      .object({
        verifier_id: z.string(),
        verifier_version: z.string(),
        checks: z.array(z.string()),
        max_duration_ms: z.number().int().nonnegative(),
        max_result_bytes: z.number().int().nonnegative(),
      })
      .passthrough(),
    safety_boundary: z
      .object({
        read_only: z.boolean(),
        allowed_effects: z.array(z.string()),
        required_guards: z.array(z.string()),
      })
      .passthrough(),
  })
  .passthrough()

const builtinToolInstallationSchema = z
  .object({
    tool_identifier: z.string(),
    handler_version: z.string(),
    implementation_digest: z.string(),
    installation_status: z.enum(["INSTALLED", "MISSING", "DRIFTED"]),
    safe_health_summary: z.string().default(""),
    first_seen_at: z.string(),
    last_seen_at: z.string(),
  })
  .passthrough()

const builtinToolVerificationSchema = z
  .object({
    id: z.string(),
    tool_identifier: z.string(),
    handler_version: z.string(),
    implementation_digest: z.string(),
    verifier_version: z.string(),
    normalized_input_hash: z.string(),
    status: z.enum(["PASSED", "FAILED", "BLOCKED"]),
    result_summary: z.record(z.string(), z.unknown()).default({}),
    safe_error_summary: z.string().default(""),
    verified_by: z.string(),
    verified_at: z.string(),
  })
  .passthrough()

const builtinToolDependenciesSchema = z
  .object({
    active_agent_publications: z.number().int().nonnegative(),
    active_application_publications: z.number().int().nonnegative(),
    recoverable_jobs: z.number().int().nonnegative(),
  })
  .passthrough()

const builtinToolLifecycleAuditSchema = z
  .object({
    id: z.string(),
    tool_release_id: z.string(),
    previous_status: z
      .enum(["ACTIVE", "DEPRECATED", "DISABLED", "ARCHIVED"])
      .nullable(),
    new_status: z.enum(["ACTIVE", "DEPRECATED", "DISABLED", "ARCHIVED"]),
    reason_code: z.string(),
    safe_summary: z.string().default(""),
    actor_id: z.string(),
    correlation_id: z.string(),
    occurred_at: z.string(),
  })
  .passthrough()

const builtinToolReleaseSchema = z
  .object({
    id: z.string(),
    tool_identifier: z.string(),
    release_revision: z.number().int().positive(),
    tool_semantic_version: z.string(),
    handler_version: z.string(),
    implementation_digest: z.string(),
    manifest_hash: z.string(),
    public_schema_hash: z.string(),
    verification_id: z.string(),
    status: z.enum(["ACTIVE", "DEPRECATED", "DISABLED", "ARCHIVED"]),
    published_by: z.string(),
    published_at: z.string(),
    deprecated_by: z.string().default(""),
    deprecated_at: z.string().nullish(),
    disabled_by: z.string().default(""),
    disabled_at: z.string().nullish(),
    archived_by: z.string().default(""),
    archived_at: z.string().nullish(),
    dependencies: builtinToolDependenciesSchema.default({
      active_agent_publications: 0,
      active_application_publications: 0,
      recoverable_jobs: 0,
    }),
    lifecycle_audit: z.array(builtinToolLifecycleAuditSchema).default([]),
  })
  .passthrough()

const builtinToolSchema = z
  .object({
    manifest: builtinToolManifestSchema,
    code_implementation_digest: z.string(),
    installation: builtinToolInstallationSchema.nullable(),
    verifications: z.array(builtinToolVerificationSchema),
    releases: z.array(builtinToolReleaseSchema),
    effective_status: z.enum([
      "NOT_RECONCILED",
      "INSTALLED",
      "MISSING",
      "DRIFTED",
      "CALLABLE",
      "LIFECYCLE_BLOCKED",
      "UNPUBLISHED",
    ]),
  })
  .passthrough()

const workshopPartitionDraftSchema = z
  .object({
    policy_id: z.string(),
    draft_revision: z.number().int().positive(),
    database_rule_enabled: z.boolean(),
    database_table_prefix: z.string().nullish(),
    redis_rule_enabled: z.boolean(),
    redis_prefixes: z.array(z.string()),
    content_hash: z.string(),
    status: z.enum(["DRAFT", "VERIFIED"]),
    updated_at: z.string(),
  })
  .passthrough()

const workshopPartitionRevisionSchema = z
  .object({
    id: z.string(),
    policy_id: z.string(),
    revision: z.number().int().positive(),
    database_rule_enabled: z.boolean(),
    database_table_prefix: z.string().nullish(),
    redis_rule_enabled: z.boolean(),
    redis_prefixes: z.array(z.string()),
    content_hash: z.string(),
    verification_id: z.string(),
    status: z.literal("PUBLISHED"),
    published_at: z.string(),
  })
  .passthrough()

const workshopPartitionPolicyIdentitySchema = z
  .object({
    id: z.string(),
    code: z.string(),
    environment_code: z.string(),
    base_code: z.string(),
    workshop_code: z.string(),
    status: z.string(),
    revision: z.number().int().positive(),
  })
  .passthrough()

const workshopPartitionPolicySchema = workshopPartitionPolicyIdentitySchema
  .extend({
    draft: workshopPartitionDraftSchema.nullable(),
    revisions: z.array(workshopPartitionRevisionSchema),
  })
  .passthrough()

const workshopPartitionVerificationSchema = z
  .object({
    id: z.string(),
    policy_id: z.string(),
    draft_revision: z.number().int().positive(),
    status: z.enum(["PASSED", "FAILED", "BLOCKED"]),
    database_summary: z.record(z.string(), z.unknown()).default({}),
    redis_summary: z.record(z.string(), z.unknown()).default({}),
    zero_match_warning: z.boolean(),
    safe_error_summary: z.string().default(""),
    verified_at: z.string(),
  })
  .passthrough()

const lokiConditionSchema = z.object({ key: z.string(), value: z.string() })

const lokiScopeDraftSchema = z
  .object({
    policy_id: z.string(),
    draft_revision: z.number().int().positive(),
    resource_id: z.string().default(""),
    resource_code: z.string().default(""),
    resource_revision_id: z.string(),
    resource_revision: z.number().int().nonnegative().default(0),
    conditions: z.array(lokiConditionSchema),
    content_hash: z.string(),
    status: z.enum(["DRAFT", "VERIFIED"]),
    updated_at: z.string(),
  })
  .passthrough()

const lokiScopeRevisionSchema = z
  .object({
    id: z.string(),
    policy_id: z.string(),
    revision: z.number().int().positive(),
    resource_id: z.string().default(""),
    resource_code: z.string().default(""),
    resource_revision_id: z.string(),
    resource_revision: z.number().int().nonnegative().default(0),
    conditions: z.array(lokiConditionSchema),
    content_hash: z.string(),
    verification_id: z.string(),
    status: z.literal("PUBLISHED"),
    health_status: z.enum(["HEALTHY", "EMPTY", "DEGRADED"]),
    published_at: z.string(),
  })
  .passthrough()

const lokiScopePolicyIdentitySchema = z
  .object({
    id: z.string(),
    code: z.string(),
    environment_code: z.string(),
    base_code: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    status: z.string(),
    revision: z.number().int().positive(),
    resource_ids: z.array(z.string()).default([]),
    draft_resource_revision_id: z.string().default(""),
    published_resource_revision_id: z.string().default(""),
    published_policy_revision: z.number().int().nonnegative().default(0),
  })
  .passthrough()

const lokiScopeApplicationUsageSchema = z
  .object({
    policy_revision_id: z.string(),
    policy_revision: z.number().int().positive(),
    application_id: z.string(),
    application_code: z.string(),
    application_name: z.string(),
    application_publication_id: z.string(),
    application_publication_revision: z.number().int().positive(),
    resource_slot: z.string(),
    target_key: z.string(),
    deployment_environment: z.string().default(""),
    active: z.boolean().default(false),
  })
  .passthrough()

const lokiScopePolicySchema = lokiScopePolicyIdentitySchema
  .extend({
    draft: lokiScopeDraftSchema.nullable(),
    revisions: z.array(lokiScopeRevisionSchema),
    application_usages: z.array(lokiScopeApplicationUsageSchema).default([]),
  })
  .passthrough()

const lokiScopeVerificationSchema = z
  .object({
    id: z.string(),
    policy_id: z.string(),
    draft_revision: z.number().int().positive(),
    resource_revision_id: z.string(),
    status: z.enum(["PASSED", "FAILED", "BLOCKED"]),
    match_count: z.number().int().nonnegative(),
    truncated: z.boolean(),
    zero_match_warning: z.boolean(),
    result_summary: z.record(z.string(), z.unknown()).default({}),
    safe_error_summary: z.string().default(""),
    verified_at: z.string(),
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
export const runtimeResponseSchema = z.object({ runtime: runtimeStatusSchema })
export const builtinToolListResponseSchema = z.object({
  tools: z.array(builtinToolSchema),
})
export const builtinToolDetailResponseSchema = z.object({
  tool: builtinToolSchema,
})
export const builtinToolReconcileResponseSchema = z.object({
  summary: z.object({
    installed: z.number().int().nonnegative(),
    missing: z.number().int().nonnegative(),
    drifted: z.number().int().nonnegative(),
  }),
})
export const builtinToolVerificationResponseSchema = z.object({
  verification: builtinToolVerificationSchema,
})
export const builtinToolReleaseResponseSchema = z.object({
  release: builtinToolReleaseSchema,
})
export const workshopPartitionPolicyListResponseSchema = z.object({
  policies: z.array(workshopPartitionPolicyIdentitySchema),
})
export const workshopPartitionPolicyResponseSchema = z.object({
  policy: workshopPartitionPolicySchema,
})
export const workshopPartitionDraftResponseSchema = z.object({
  draft: workshopPartitionDraftSchema,
})
export const workshopPartitionVerificationResponseSchema = z.object({
  verification: workshopPartitionVerificationSchema,
})
export const workshopPartitionRevisionResponseSchema = z.object({
  revision: workshopPartitionRevisionSchema,
})
export const lokiScopePolicyListResponseSchema = z.object({
  policies: z.array(lokiScopePolicyIdentitySchema),
})
export const lokiScopePolicyResponseSchema = z.object({
  policy: lokiScopePolicySchema,
})
export const lokiScopeDraftResponseSchema = z.object({
  draft: lokiScopeDraftSchema,
})
export const lokiScopeVerificationResponseSchema = z.object({
  verification: lokiScopeVerificationSchema,
})
export const lokiScopeRevisionResponseSchema = z.object({
  revision: lokiScopeRevisionSchema,
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
export type BuiltinTool = z.infer<typeof builtinToolSchema>
export type BuiltinToolManifest = z.infer<typeof builtinToolManifestSchema>
export type BuiltinToolVerification = z.infer<
  typeof builtinToolVerificationSchema
>
export type BuiltinToolRelease = z.infer<typeof builtinToolReleaseSchema>
export type BuiltinToolLifecycleStatus = BuiltinToolRelease["status"]
export type WorkshopPartitionPolicy = z.infer<
  typeof workshopPartitionPolicySchema
>
export type WorkshopPartitionPolicyIdentity = z.infer<
  typeof workshopPartitionPolicyIdentitySchema
>
export type WorkshopPartitionVerification = z.infer<
  typeof workshopPartitionVerificationSchema
>
export type LokiScopePolicy = z.infer<typeof lokiScopePolicySchema>
export type LokiScopePolicyIdentity = z.infer<
  typeof lokiScopePolicyIdentitySchema
>
export type LokiScopeVerification = z.infer<typeof lokiScopeVerificationSchema>
export type LokiCondition = z.infer<typeof lokiConditionSchema>

export type ResourceFormInput = {
  code: string
  name: string
  resource_kind: "database" | "redis" | "loki"
  scope_type: "global" | "environment" | "base" | "workshop"
  environment_code: string
  base_code: string
  workshop_code: string
  provider_type: "mysql" | "sqlserver" | "oracle" | "redis" | "loki"
  config: Record<string, unknown>
  secret_refs: Record<string, string>
}
