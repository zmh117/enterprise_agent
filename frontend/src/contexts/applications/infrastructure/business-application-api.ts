import type {
  ApplicationCatalog,
  ApplicationDraftInput,
  ApplicationPublication,
  BusinessApplicationDetail,
  BusinessApplicationSummary,
  Environment,
} from "@/contexts/applications/domain/business-application"
import type { LifecycleStatus } from "@/contexts/agents/domain/agent"
import { apiRequest, createIdempotencyKey } from "@/shared/api/api-client"

const root = "/api/admin/business-applications"
const headers = (scope: string) => ({
  "Idempotency-Key": createIdempotencyKey(scope),
})

export function listBusinessApplications() {
  return apiRequest<{
    items: BusinessApplicationSummary[]
    permissions: { can_create: boolean }
  }>(root)
}

export async function getBusinessApplication(code: string) {
  const response = await apiRequest<{ application: BusinessApplicationDetail }>(
    `${root}/${encodeURIComponent(code)}`
  )
  return response.application
}

export async function createBusinessApplication(input: {
  code: string
  name: string
  description: string
  project_code: string
  owner_user_id: string
}) {
  const response = await apiRequest<{ application: BusinessApplicationDetail }>(
    root,
    {
      method: "POST",
      headers: headers("application-create"),
      body: { expected_revision: 0, ...input },
    }
  )
  return response.application
}

export async function updateBusinessApplication(
  code: string,
  input: {
    expectedRevision: number
    name: string
    description: string
    project_code: string
    owner_user_id: string
    status: LifecycleStatus
  }
) {
  const { expectedRevision, ...value } = input
  const response = await apiRequest<{ application: BusinessApplicationDetail }>(
    `${root}/${encodeURIComponent(code)}`,
    {
      method: "PUT",
      headers: headers("application-update"),
      body: { expected_revision: expectedRevision, ...value },
    }
  )
  return response.application
}

export async function saveApplicationDraft(
  code: string,
  expectedRevision: number,
  input: ApplicationDraftInput
) {
  const response = await apiRequest<{ revision: Record<string, unknown> }>(
    `${root}/${encodeURIComponent(code)}/draft`,
    {
      method: "PUT",
      headers: headers("application-draft"),
      body: { expected_revision: expectedRevision, ...input },
    }
  )
  return response.revision
}

export async function validateBusinessApplication(
  code: string,
  revisionId: string,
  expectedRevision: number
) {
  const response = await apiRequest<{ revision: Record<string, unknown> }>(
    `${root}/${encodeURIComponent(code)}/validate`,
    {
      method: "POST",
      headers: headers("application-validate"),
      body: {
        revision_id: revisionId,
        expected_revision: expectedRevision,
      },
    }
  )
  return response.revision
}

export async function publishBusinessApplication(
  code: string,
  revisionId: string,
  expectedRevision: number
) {
  const response = await apiRequest<{ publication: ApplicationPublication }>(
    `${root}/${encodeURIComponent(code)}/publish`,
    {
      method: "POST",
      headers: headers("application-publish"),
      body: {
        revision_id: revisionId,
        expected_revision: expectedRevision,
      },
    }
  )
  return response.publication
}

export async function activateBusinessApplication(
  code: string,
  environment: Environment,
  publicationId: string,
  expectedRevision: number
) {
  const response = await apiRequest<{ deployment: Record<string, unknown> }>(
    `${root}/${encodeURIComponent(code)}/environments/${environment}/activate`,
    {
      method: "POST",
      headers: headers("application-activate"),
      body: {
        publication_id: publicationId,
        expected_revision: expectedRevision,
      },
    }
  )
  return response.deployment
}

export async function deactivateBusinessApplication(
  code: string,
  environment: Environment,
  expectedRevision: number
) {
  const response = await apiRequest<{ deployment: Record<string, unknown> }>(
    `${root}/${encodeURIComponent(code)}/environments/${environment}/deactivate`,
    {
      method: "POST",
      headers: headers("application-deactivate"),
      body: { expected_revision: expectedRevision },
    }
  )
  return response.deployment
}

export async function getApplicationEffective(
  code: string,
  environment: Environment
) {
  return apiRequest<Record<string, unknown>>(
    `${root}/${encodeURIComponent(code)}/environments/${environment}/effective`
  )
}

export function getApplicationCatalog(code: string) {
  return apiRequest<ApplicationCatalog>(
    `${root}/${encodeURIComponent(code)}/catalog`
  )
}
