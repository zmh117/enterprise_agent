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
  runtime_kind: z.enum(["python-v1", "typescript-v1"]).optional(),
  direction: z.string(),
  component_type: z.string(),
})

export const catalogSchema = z.object({
  agents: z.array(componentReferenceSchema),
  workflows: z.array(componentReferenceSchema),
  connectors: z.array(componentReferenceSchema),
  capabilities: z.array(componentReferenceSchema),
  capability_catalog_connected: z.boolean(),
  api_capabilities_by_agent_publication: z
    .record(
      z.string(),
      z.array(
        z
          .object({
            identifier: z.string(),
            release_id: z.string(),
            description: z.string(),
            release_revision: z.number(),
            status: z.string(),
            release_note: z.string().default(""),
            deprecation_reason: z.string().default(""),
            replacement_release_id: z.string().nullable().optional(),
            selectable: z.boolean(),
          })
          .passthrough()
      )
    )
    .default({}),
  builtin_tools_by_agent_publication: z
    .record(
      z.string(),
      z.array(
        z
          .object({
            tool_identifier: z.string(),
            tool_release_id: z.string(),
            release_revision: z.number().int().positive(),
            tool_semantic_version: z.string(),
            handler_version: z.string(),
            implementation_digest: z.string(),
            public_schema_hash: z.string(),
            display_name: z.string(),
            model_description: z.string(),
            resource_slots: z.array(
              z.object({
                code: z.string(),
                resource_kind: z.enum(["database", "redis", "loki"]),
                required: z.boolean(),
                allowed_scope_types: z.array(
                  z.enum(["environment", "base", "workshop"])
                ),
              })
            ),
            release_status: z.string(),
            installation_status: z.string(),
            selectable: z.boolean(),
          })
          .passthrough()
      )
    )
    .default({}),
  resource_revisions: z
    .array(
      z
        .object({
          resource_revision_id: z.string(),
          resource_revision: z.number().int().positive(),
          resource_code: z.string(),
          resource_name: z.string(),
          resource_kind: z.enum(["database", "redis", "loki"]),
          scope_type: z.enum(["global", "environment", "base", "workshop"]),
          environment_code: z.string(),
          base_code: z.string(),
          workshop_code: z.string(),
          content_hash: z.string(),
        })
        .passthrough()
    )
    .default([]),
  workshop_policy_revisions: z
    .array(
      z
        .object({
          policy_revision_id: z.string(),
          policy_revision: z.number().int().positive(),
          policy_code: z.string(),
          environment_code: z.string(),
          base_code: z.string(),
          workshop_code: z.string(),
          database_rule_enabled: z.boolean(),
          redis_rule_enabled: z.boolean(),
          content_hash: z.string(),
        })
        .passthrough()
    )
    .default([]),
  loki_policy_revisions: z
    .array(
      z
        .object({
          policy_revision_id: z.string(),
          policy_revision: z.number().int().positive(),
          policy_code: z.string(),
          resource_revision_id: z.string(),
          environment_code: z.string(),
          base_code: z.string(),
          health_status: z.enum(["HEALTHY", "EMPTY", "DEGRADED"]),
          conditions: z.array(z.object({ key: z.string(), value: z.string() })),
          content_hash: z.string(),
        })
        .passthrough()
    )
    .default([]),
  target_paths: z
    .array(
      z.object({
        target_scope_type: z.enum(["environment", "base", "workshop"]),
        environment_code: z.string(),
        base_code: z.string(),
        workshop_code: z.string(),
        display_name: z.string(),
      })
    )
    .default([]),
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
