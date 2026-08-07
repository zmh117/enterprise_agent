import {
  baseResponseSchema,
  builtinToolDetailResponseSchema,
  builtinToolListResponseSchema,
  builtinToolReconcileResponseSchema,
  builtinToolReleaseResponseSchema,
  builtinToolVerificationResponseSchema,
  environmentResponseSchema,
  lokiDraftTestResponseSchema,
  lokiLabelValuesResponseSchema,
  lokiScopeDraftResponseSchema,
  lokiScopePolicyListResponseSchema,
  lokiScopePolicyResponseSchema,
  lokiScopeRevisionResponseSchema,
  lokiScopeVerificationResponseSchema,
  resourceCreateResponseSchema,
  resourceDraftResponseSchema,
  resourceListResponseSchema,
  resourceRevisionResponseSchema,
  runtimeResponseSchema,
  secretListResponseSchema,
  secretResponseSchema,
  secretUsageResponseSchema,
  verificationResponseSchema,
  workshopPartitionDraftResponseSchema,
  workshopPartitionPolicyListResponseSchema,
  workshopPartitionPolicyResponseSchema,
  workshopPartitionRevisionResponseSchema,
  workshopPartitionVerificationResponseSchema,
  workshopResponseSchema,
  type ResourceFormInput,
  type BuiltinToolLifecycleStatus,
  type LokiCondition,
} from "@/contexts/platform-governance/domain/platform-governance"
import { apiRequest } from "@/shared/api/api-client"

export async function listPlatformSecrets() {
  return secretListResponseSchema.parse(
    await apiRequest("/api/platform/secrets")
  ).secrets
}

export async function createPlatformSecret(input: {
  code: string
  purpose: string
  value: string
}) {
  return secretResponseSchema.parse(
    await apiRequest("/api/platform/secrets", {
      method: "POST",
      body: input,
    })
  ).secret
}

export async function rotatePlatformSecret(code: string, value: string) {
  return secretResponseSchema.parse(
    await apiRequest(
      `/api/platform/secrets/${encodeURIComponent(code)}/rotate`,
      { method: "POST", body: { value } }
    )
  ).secret
}

export async function disablePlatformSecret(code: string) {
  return secretResponseSchema.parse(
    await apiRequest(
      `/api/platform/secrets/${encodeURIComponent(code)}/disable`,
      { method: "POST" }
    )
  ).secret
}

export async function getPlatformSecretUsage(code: string) {
  return secretUsageResponseSchema.parse(
    await apiRequest(`/api/platform/secrets/${encodeURIComponent(code)}/usage`)
  ).usage
}

export async function listGovernedResources() {
  return resourceListResponseSchema.parse(
    await apiRequest("/api/platform/resources")
  ).resources
}

export async function createGovernedResource(input: ResourceFormInput) {
  return resourceCreateResponseSchema.parse(
    await apiRequest("/api/platform/resources", {
      method: "POST",
      body: input,
    })
  )
}

export async function saveGovernedResourceDraft(
  code: string,
  input: ResourceFormInput & { expected_revision: number }
) {
  return resourceDraftResponseSchema.parse(
    await apiRequest(
      `/api/platform/resources/${encodeURIComponent(code)}/draft`,
      { method: "PUT", body: input }
    )
  ).draft
}

export async function deleteGovernedResourceDraft(
  code: string,
  expectedRevision: number
) {
  return apiRequest<{ deleted: boolean }>(
    `/api/platform/resources/${encodeURIComponent(code)}/draft?expected_revision=${expectedRevision}`,
    { method: "DELETE" }
  )
}

export async function verifyGovernedResource(code: string) {
  return verificationResponseSchema.parse(
    await apiRequest(
      `/api/platform/resources/${encodeURIComponent(code)}/verify`,
      { method: "POST" }
    )
  ).verification
}

export async function publishGovernedResource(code: string) {
  return resourceRevisionResponseSchema.parse(
    await apiRequest(
      `/api/platform/resources/${encodeURIComponent(code)}/publish`,
      { method: "POST" }
    )
  ).revision
}

export async function createDraftFromRevision(
  code: string,
  revisionId: string
) {
  return resourceDraftResponseSchema.parse(
    await apiRequest(
      `/api/platform/resources/${encodeURIComponent(code)}/draft/from-revision`,
      { method: "POST", body: { revision_id: revisionId } }
    )
  ).draft
}

export async function setResourceRevisionStatus(
  code: string,
  revisionId: string,
  action: "disable" | "archive"
) {
  return resourceRevisionResponseSchema.parse(
    await apiRequest(
      `/api/platform/resources/${encodeURIComponent(code)}/revisions/${encodeURIComponent(revisionId)}/${action}`,
      { method: "POST" }
    )
  ).revision
}

export async function listEnvironments() {
  return environmentResponseSchema.parse(
    await apiRequest("/api/platform/environments?include_disabled=false")
  ).environments
}

export async function listBases() {
  return baseResponseSchema.parse(
    await apiRequest("/api/platform/bases?include_disabled=false")
  ).bases
}

export async function listWorkshops() {
  return workshopResponseSchema.parse(
    await apiRequest("/api/platform/workshops?include_disabled=false")
  ).workshops
}

export async function getRuntimeGenerationStatus() {
  return runtimeResponseSchema.parse(
    await apiRequest("/api/platform/runtime-generation/status")
  ).runtime
}

export async function listBuiltinTools() {
  return builtinToolListResponseSchema.parse(
    await apiRequest("/api/platform/builtin-tools")
  ).tools
}

export async function getBuiltinTool(toolIdentifier: string) {
  return builtinToolDetailResponseSchema.parse(
    await apiRequest(
      `/api/platform/builtin-tools/${encodeURIComponent(toolIdentifier)}`
    )
  ).tool
}

export async function reconcileBuiltinTools() {
  return builtinToolReconcileResponseSchema.parse(
    await apiRequest("/api/platform/builtin-tools/reconcile", {
      method: "POST",
    })
  ).summary
}

export async function verifyBuiltinTool(
  toolIdentifier: string,
  handlerVersion: string
) {
  return builtinToolVerificationResponseSchema.parse(
    await apiRequest(
      `/api/platform/builtin-tools/${encodeURIComponent(toolIdentifier)}/verify`,
      { method: "POST", body: { handler_version: handlerVersion } }
    )
  ).verification
}

export async function publishBuiltinTool(input: {
  toolIdentifier: string
  handlerVersion: string
  verificationId: string
  idempotencyKey: string
}) {
  return builtinToolReleaseResponseSchema.parse(
    await apiRequest(
      `/api/platform/builtin-tools/${encodeURIComponent(input.toolIdentifier)}/publish`,
      {
        method: "POST",
        body: {
          handler_version: input.handlerVersion,
          verification_id: input.verificationId,
          idempotency_key: input.idempotencyKey,
        },
      }
    )
  ).release
}

export async function setBuiltinToolReleaseLifecycle(input: {
  releaseId: string
  status: BuiltinToolLifecycleStatus
  reasonCode: string
  verificationId?: string
}) {
  return builtinToolReleaseResponseSchema.parse(
    await apiRequest(
      `/api/platform/builtin-tool-releases/${encodeURIComponent(input.releaseId)}/lifecycle`,
      {
        method: "POST",
        body: {
          status: input.status,
          reason_code: input.reasonCode,
          ...(input.verificationId
            ? { verification_id: input.verificationId }
            : {}),
        },
      }
    )
  ).release
}

export async function testLokiResourceDraft(code: string) {
  return lokiDraftTestResponseSchema.parse(
    await apiRequest(
      `/api/platform/resources/${encodeURIComponent(code)}/loki/test`,
      { method: "POST", body: { minutes: 15, limit: 64 } }
    )
  )
}

export async function discoverLokiLabelValues(input: {
  code: string
  testSessionId: string
  label: string
  selectedConditions: Record<string, string>
}) {
  return lokiLabelValuesResponseSchema.parse(
    await apiRequest(
      `/api/platform/resources/${encodeURIComponent(input.code)}/loki/label-values`,
      {
        method: "POST",
        body: {
          test_session_id: input.testSessionId,
          label: input.label,
          selected_conditions: input.selectedConditions,
          minutes: 15,
          limit: 100,
        },
      }
    )
  )
}

export async function listWorkshopPartitionPolicies() {
  return workshopPartitionPolicyListResponseSchema.parse(
    await apiRequest("/api/platform/workshop-partition-policies")
  ).policies
}

export async function getWorkshopPartitionPolicy(code: string) {
  return workshopPartitionPolicyResponseSchema.parse(
    await apiRequest(
      `/api/platform/workshop-partition-policies/${encodeURIComponent(code)}`
    )
  ).policy
}

export async function createWorkshopPartitionPolicy(input: {
  code: string
  environment_code: string
  base_code: string
  workshop_code: string
  database_rule_enabled: boolean
  database_table_prefix: string
  redis_rule_enabled: boolean
  redis_prefixes: string[]
}) {
  return workshopPartitionPolicyResponseSchema.parse(
    await apiRequest("/api/platform/workshop-partition-policies", {
      method: "POST",
      body: input,
    })
  ).policy
}

export async function saveWorkshopPartitionPolicyDraft(input: {
  code: string
  expectedDraftRevision: number
  databaseRuleEnabled: boolean
  databaseTablePrefix: string
  redisRuleEnabled: boolean
  redisPrefixes: string[]
}) {
  return workshopPartitionDraftResponseSchema.parse(
    await apiRequest(
      `/api/platform/workshop-partition-policies/${encodeURIComponent(input.code)}/draft`,
      {
        method: "PUT",
        body: {
          expected_draft_revision: input.expectedDraftRevision,
          database_rule_enabled: input.databaseRuleEnabled,
          database_table_prefix: input.databaseTablePrefix,
          redis_rule_enabled: input.redisRuleEnabled,
          redis_prefixes: input.redisPrefixes,
        },
      }
    )
  ).draft
}

export async function verifyWorkshopPartitionPolicy(input: {
  code: string
  expectedDraftRevision: number
  redisResourceRevisionId?: string
}) {
  return workshopPartitionVerificationResponseSchema.parse(
    await apiRequest(
      `/api/platform/workshop-partition-policies/${encodeURIComponent(input.code)}/verify`,
      {
        method: "POST",
        body: {
          expected_draft_revision: input.expectedDraftRevision,
          ...(input.redisResourceRevisionId
            ? { redis_resource_revision_id: input.redisResourceRevisionId }
            : {}),
        },
      }
    )
  ).verification
}

export async function publishWorkshopPartitionPolicy(input: {
  code: string
  verificationId: string
  expectedPolicyRevision: number
}) {
  return workshopPartitionRevisionResponseSchema.parse(
    await apiRequest(
      `/api/platform/workshop-partition-policies/${encodeURIComponent(input.code)}/publish`,
      {
        method: "POST",
        body: {
          verification_id: input.verificationId,
          expected_policy_revision: input.expectedPolicyRevision,
        },
      }
    )
  ).revision
}

export async function copyWorkshopPartitionPolicyRevision(input: {
  code: string
  sourceRevisionId: string
  expectedPolicyRevision: number
}) {
  return workshopPartitionDraftResponseSchema.parse(
    await apiRequest(
      `/api/platform/workshop-partition-policies/${encodeURIComponent(input.code)}/draft/from-revision`,
      {
        method: "POST",
        body: {
          source_revision_id: input.sourceRevisionId,
          expected_policy_revision: input.expectedPolicyRevision,
        },
      }
    )
  ).draft
}

export async function listLokiScopePolicies() {
  return lokiScopePolicyListResponseSchema.parse(
    await apiRequest("/api/platform/loki-scope-policies")
  ).policies
}

export async function getLokiScopePolicy(code: string) {
  return lokiScopePolicyResponseSchema.parse(
    await apiRequest(
      `/api/platform/loki-scope-policies/${encodeURIComponent(code)}`
    )
  ).policy
}

export async function createLokiScopePolicy(input: {
  code: string
  environment_code: string
  base_code: string
  resource_revision_id: string
  conditions: LokiCondition[]
}) {
  return lokiScopePolicyResponseSchema.parse(
    await apiRequest("/api/platform/loki-scope-policies", {
      method: "POST",
      body: input,
    })
  ).policy
}

export async function saveLokiScopePolicyDraft(input: {
  code: string
  expectedDraftRevision: number
  resourceRevisionId: string
  conditions: LokiCondition[]
}) {
  return lokiScopeDraftResponseSchema.parse(
    await apiRequest(
      `/api/platform/loki-scope-policies/${encodeURIComponent(input.code)}/draft`,
      {
        method: "PUT",
        body: {
          expected_draft_revision: input.expectedDraftRevision,
          resource_revision_id: input.resourceRevisionId,
          conditions: input.conditions,
        },
      }
    )
  ).draft
}

export async function verifyLokiScopePolicy(input: {
  code: string
  expectedDraftRevision: number
}) {
  return lokiScopeVerificationResponseSchema.parse(
    await apiRequest(
      `/api/platform/loki-scope-policies/${encodeURIComponent(input.code)}/verify`,
      {
        method: "POST",
        body: { expected_draft_revision: input.expectedDraftRevision },
      }
    )
  ).verification
}

export async function publishLokiScopePolicy(input: {
  code: string
  verificationId: string
  expectedPolicyRevision: number
}) {
  return lokiScopeRevisionResponseSchema.parse(
    await apiRequest(
      `/api/platform/loki-scope-policies/${encodeURIComponent(input.code)}/publish`,
      {
        method: "POST",
        body: {
          verification_id: input.verificationId,
          expected_policy_revision: input.expectedPolicyRevision,
        },
      }
    )
  ).revision
}

export async function copyLokiScopePolicyRevision(input: {
  code: string
  sourceRevisionId: string
  expectedPolicyRevision: number
}) {
  return lokiScopeDraftResponseSchema.parse(
    await apiRequest(
      `/api/platform/loki-scope-policies/${encodeURIComponent(input.code)}/draft/from-revision`,
      {
        method: "POST",
        body: {
          source_revision_id: input.sourceRevisionId,
          expected_policy_revision: input.expectedPolicyRevision,
        },
      }
    )
  ).draft
}
