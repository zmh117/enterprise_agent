import {
  baseResponseSchema,
  environmentResponseSchema,
  resourceCreateResponseSchema,
  resourceDraftResponseSchema,
  resourceListResponseSchema,
  resourceRevisionResponseSchema,
  runtimeResponseSchema,
  secretListResponseSchema,
  secretResponseSchema,
  secretUsageResponseSchema,
  verificationResponseSchema,
  workshopResponseSchema,
  type ResourceFormInput,
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
