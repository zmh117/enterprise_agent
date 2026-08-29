import { z } from "zod"

import {
  applicationSummarySchema,
  businessApplicationSchema,
  deploymentSchema,
  publicationSchema,
  revisionSchema,
  runtimeStateSchema,
  type CreateApplicationInput,
  type SaveDraftInput,
} from "@/contexts/applications/domain/business-application"
import { apiRequest } from "@/shared/api/api-client"
import { mcpServerCodeSchema } from "@/shared/domain/mcp-server-code"

const listResponseSchema = runtimeStateSchema.extend({
  items: z.array(applicationSummarySchema),
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
  runtime_kind: z.preprocess(
    (value) => (value === "" || value === null ? undefined : value),
    z.literal("python-v1").optional()
  ),
  runtime_protocol_versions: z.array(z.literal("1.4")).default([]),
  direction: z.string(),
  component_type: z.string(),
})

export const catalogSchema = z.object({
  agents: z.array(componentReferenceSchema),
  workflows: z.array(componentReferenceSchema),
  connectors: z.array(componentReferenceSchema),
  document_processing_profiles: z
    .array(
      z.object({
        code: z.enum(["NONE", "docling-layout-ocr-v2"]),
        version: z.string(),
        hash: z.string(),
        label: z.string(),
        source_format_codes: z.array(z.string()),
        output_kinds: z.array(z.string()),
        selectable: z.boolean().default(true),
        limits: z
          .object({
            max_source_bytes: z.number().int().positive(),
            max_pdf_pages: z.number().int().positive(),
            processing_timeout_seconds: z.number().int().positive(),
          })
          .optional(),
        document_processing_status: z.enum([
          "DISABLED",
          "CONFIGURED_UNAVAILABLE",
          "READY",
        ]),
        document_processing_reason_code: z.string(),
      })
    )
    .default([]),
  mcp_tools_by_agent_publication: z
    .record(
      z.string(),
      z.array(
        z.object({
          server_code: mcpServerCodeSchema,
          tool_identifier: z.string(),
          schema_hash: z.string(),
          description: z.string(),
          resource_kind: z.string(),
          effect: z.enum(["read", "mutation"]).default("read"),
          confirmation_policy: z.string().default("none"),
        })
      )
    )
    .default({}),
})

export async function listApplications() {
  return listResponseSchema.parse(
    await apiRequest("/api/admin/business-applications")
  ).items
}

export async function getApplication(code: string) {
  return detailResponseSchema.parse(
    await apiRequest(
      `/api/admin/business-applications/${encodeURIComponent(code)}`
    )
  ).application
}

export async function createApplication(input: CreateApplicationInput) {
  return detailResponseSchema.parse(
    await apiRequest("/api/admin/business-applications", {
      method: "POST",
      body: input,
    })
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
  }
) {
  return detailResponseSchema.parse(
    await apiRequest(
      `/api/admin/business-applications/${encodeURIComponent(code)}`,
      {
        method: "PUT",
        body: input,
      }
    )
  ).application
}

export async function saveDraft(code: string, input: SaveDraftInput) {
  const response = runtimeStateSchema
    .extend({ revision: revisionSchema })
    .parse(
      await apiRequest(
        `/api/admin/business-applications/${encodeURIComponent(code)}/draft`,
        { method: "PUT", body: input }
      )
    )
  return response.revision
}

export async function validateDraft(code: string, revisionId: string) {
  return z
    .object({ revision: revisionSchema })
    .parse(
      await apiRequest(
        `/api/admin/business-applications/${encodeURIComponent(code)}/validate`,
        { method: "POST", body: { revision_id: revisionId } }
      )
    ).revision
}

export async function publishDraft(code: string, revisionId: string) {
  return runtimeStateSchema
    .extend({
      publication: publicationSchema,
    })
    .parse(
      await apiRequest(
        `/api/admin/business-applications/${encodeURIComponent(code)}/publish`,
        { method: "POST", body: { revision_id: revisionId } }
      )
    ).publication
}

export async function activatePublication(
  code: string,
  publicationId: string,
  expectedRevision: number
) {
  return z.object({ deployment: deploymentSchema }).parse(
    await apiRequest(
      `/api/admin/business-applications/${encodeURIComponent(code)}/environments/local/activate`,
      {
        method: "POST",
        body: {
          publication_id: publicationId,
          expected_revision: expectedRevision,
        },
      }
    )
  ).deployment
}

export async function deactivateLocalDeployment(
  code: string,
  expectedRevision: number
) {
  return z
    .object({ deployment: deploymentSchema })
    .parse(
      await apiRequest(
        `/api/admin/business-applications/${encodeURIComponent(code)}/environments/local/deactivate`,
        { method: "POST", body: { expected_revision: expectedRevision } }
      )
    ).deployment
}

export async function getCatalog(code: string) {
  return catalogSchema.parse(
    await apiRequest(
      `/api/admin/business-applications/${encodeURIComponent(code)}/catalog`
    )
  )
}
