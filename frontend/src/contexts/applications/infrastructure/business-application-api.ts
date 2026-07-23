import { z } from "zod"

import {
  applicationSummarySchema,
  businessApplicationSchema,
  deploymentSchema,
  publicationSchema,
  revisionSchema,
  type CreateApplicationInput,
  type SaveDraftInput,
} from "@/contexts/applications/domain/business-application"
import { apiRequest } from "@/shared/api/api-client"

const listResponseSchema = z.object({
  items: z.array(applicationSummarySchema),
  runtime_wired: z.literal(false),
})

const detailResponseSchema = z.object({
  application: businessApplicationSchema,
})

const componentReferenceSchema = z.object({
  id: z.string(),
  code: z.string(),
  revision: z.number(),
  project_code: z.string(),
  status: z.string(),
  config_hash: z.string(),
  direction: z.string(),
  component_type: z.string(),
})

export const catalogSchema = z.object({
  agents: z.array(componentReferenceSchema),
  workflows: z.array(componentReferenceSchema),
  connectors: z.array(componentReferenceSchema),
  capabilities: z.array(z.never()),
  capability_catalog_connected: z.literal(false),
})

export async function listApplications() {
  return listResponseSchema.parse(
    await apiRequest("/api/admin/business-applications"),
  ).items
}

export async function getApplication(code: string) {
  return detailResponseSchema.parse(
    await apiRequest(`/api/admin/business-applications/${encodeURIComponent(code)}`),
  ).application
}

export async function createApplication(input: CreateApplicationInput) {
  return detailResponseSchema.parse(
    await apiRequest("/api/admin/business-applications", {
      method: "POST",
      body: input,
    }),
  ).application
}

export async function updateApplication(
  code: string,
  input: {
    expected_revision: number
    name: string
    description: string
    project_code: string
    owner_user_id: string
    status: "enabled" | "disabled" | "archived"
  },
) {
  return detailResponseSchema.parse(
    await apiRequest(`/api/admin/business-applications/${encodeURIComponent(code)}`, {
      method: "PUT",
      body: input,
    }),
  ).application
}

export async function saveDraft(code: string, input: SaveDraftInput) {
  const response = z
    .object({ revision: revisionSchema, runtime_wired: z.literal(false) })
    .parse(
      await apiRequest(
        `/api/admin/business-applications/${encodeURIComponent(code)}/draft`,
        { method: "PUT", body: input },
      ),
    )
  return response.revision
}

export async function validateDraft(code: string, revisionId: string) {
  return z
    .object({ revision: revisionSchema })
    .parse(
      await apiRequest(
        `/api/admin/business-applications/${encodeURIComponent(code)}/validate`,
        { method: "POST", body: { revision_id: revisionId } },
      ),
    ).revision
}

export async function publishDraft(code: string, revisionId: string) {
  return z
    .object({
      publication: publicationSchema,
      runtime_wired: z.literal(false),
    })
    .parse(
      await apiRequest(
        `/api/admin/business-applications/${encodeURIComponent(code)}/publish`,
        { method: "POST", body: { revision_id: revisionId } },
      ),
    ).publication
}

export async function activatePublication(
  code: string,
  environment: string,
  publicationId: string,
  expectedRevision: number,
) {
  return z
    .object({ deployment: deploymentSchema })
    .parse(
      await apiRequest(
        `/api/admin/business-applications/${encodeURIComponent(code)}/environments/${encodeURIComponent(environment)}/activate`,
        {
          method: "POST",
          body: {
            publication_id: publicationId,
            expected_revision: expectedRevision,
          },
        },
      ),
    ).deployment
}

export async function deactivateEnvironment(
  code: string,
  environment: string,
  expectedRevision: number,
) {
  return z
    .object({ deployment: deploymentSchema })
    .parse(
      await apiRequest(
        `/api/admin/business-applications/${encodeURIComponent(code)}/environments/${encodeURIComponent(environment)}/deactivate`,
        { method: "POST", body: { expected_revision: expectedRevision } },
      ),
    ).deployment
}

export async function getCatalog(code: string) {
  return catalogSchema.parse(
    await apiRequest(
      `/api/admin/business-applications/${encodeURIComponent(code)}/catalog`,
    ),
  )
}

