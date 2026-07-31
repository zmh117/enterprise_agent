import { z } from "zod"

import {
  apiCapabilitySchema,
  apiConnectionSchema,
  capabilityPreviewSchema,
  capabilityReleaseSchema,
  connectionRevisionSchema,
  type CapabilityDraftInput,
  type ConnectionDraftInput,
} from "@/contexts/api-capabilities/domain/api-capability"
import { apiRequest } from "@/shared/api/api-client"

export async function listApiConnections() {
  return z.object({ items: z.array(apiConnectionSchema) }).parse(
    await apiRequest("/api/admin/api-connections"),
  ).items
}

export async function createApiConnection(
  input: ConnectionDraftInput & { code: string; name: string },
) {
  return z.object({ connection: apiConnectionSchema }).parse(
    await apiRequest("/api/admin/api-connections", {
      method: "POST",
      body: input,
    }),
  ).connection
}

export async function saveApiConnectionDraft(
  connectionId: string,
  input: ConnectionDraftInput & { expected_revision: number },
) {
  return z.object({ connection: apiConnectionSchema }).parse(
    await apiRequest(
      `/api/admin/api-connections/${encodeURIComponent(connectionId)}/draft`,
      { method: "PUT", body: input },
    ),
  ).connection
}

export async function verifyApiConnection(
  connectionId: string,
  input: {
    draft_revision: number
    draft_hash: string
    email: string
    password: string
  },
) {
  return z.object({
    verification: z.record(z.string(), z.unknown()),
    subject: z.object({
      external_user_id: z.string(),
      display_name: z.string(),
      teams: z.array(z.object({ id: z.string(), name: z.string() })),
    }),
  }).parse(
    await apiRequest(
      `/api/admin/api-connections/${encodeURIComponent(connectionId)}/verify`,
      { method: "POST", body: input },
    ),
  )
}

export async function publishApiConnection(
  connectionId: string,
  input: { draft_revision: number; draft_hash: string },
) {
  return z.object({ revision: connectionRevisionSchema }).parse(
    await apiRequest(
      `/api/admin/api-connections/${encodeURIComponent(connectionId)}/publish`,
      { method: "POST", body: input },
    ),
  ).revision
}

export async function updateApiConnectionRevision(
  revisionId: string,
  status: "PUBLISHED" | "DISABLED" | "ARCHIVED",
) {
  return z.object({ revision: connectionRevisionSchema }).parse(
    await apiRequest(
      `/api/admin/api-connections/revisions/${encodeURIComponent(revisionId)}/status`,
      { method: "PUT", body: { status } },
    ),
  ).revision
}

export async function listApiCapabilities() {
  return z.object({ items: z.array(apiCapabilitySchema) }).parse(
    await apiRequest("/api/admin/api-capabilities"),
  ).items
}

export async function initializeOnesSearch(input: {
  connection_revision_id: string
  authentication_profile_revision_id: string
}) {
  return z.object({ capability: apiCapabilitySchema }).parse(
    await apiRequest(
      "/api/admin/api-capabilities/templates/ones-work-item-search",
      { method: "POST", body: input },
    ),
  ).capability
}

export async function saveApiCapabilityDraft(
  capabilityId: string,
  input: CapabilityDraftInput & { expected_revision: number },
) {
  return z.object({ capability: apiCapabilitySchema }).parse(
    await apiRequest(
      `/api/admin/api-capabilities/${encodeURIComponent(capabilityId)}/draft`,
      { method: "PUT", body: input },
    ),
  ).capability
}

export async function testApiCapability(
  capabilityId: string,
  input: {
    draft_revision: number
    draft_hash: string
    agent_input: Record<string, unknown>
  },
) {
  return z.object({ preview: capabilityPreviewSchema }).parse(
    await apiRequest(
      `/api/admin/api-capabilities/${encodeURIComponent(capabilityId)}/test`,
      { method: "POST", body: input },
    ),
  ).preview
}

export async function verifyApiCapability(
  capabilityId: string,
  input: {
    draft_revision: number
    draft_hash: string
    agent_input: Record<string, unknown>
  },
) {
  return z.object({
    verification: z.record(z.string(), z.unknown()),
    preview: capabilityPreviewSchema,
  }).parse(
    await apiRequest(
      `/api/admin/api-capabilities/${encodeURIComponent(capabilityId)}/verify`,
      { method: "POST", body: input },
    ),
  )
}

export async function publishApiCapability(
  capabilityId: string,
  input: {
    draft_revision: number
    draft_hash: string
    idempotency_key: string
    release_note: string
  },
) {
  return z.object({ release: capabilityReleaseSchema }).parse(
    await apiRequest(
      `/api/admin/api-capabilities/${encodeURIComponent(capabilityId)}/publish`,
      { method: "POST", body: input },
    ),
  ).release
}

export async function updateCapabilityRelease(
  releaseId: string,
  input: {
    status: "ACTIVE" | "DEPRECATED" | "DISABLED" | "ARCHIVED"
    reason: string
    replacement_release_id: string
  },
) {
  return z.object({ release: capabilityReleaseSchema }).parse(
    await apiRequest(
      `/api/admin/api-capabilities/releases/${encodeURIComponent(releaseId)}/status`,
      { method: "PUT", body: input },
    ),
  ).release
}

export async function copyCapabilityRelease(
  releaseId: string,
  expectedRevision: number,
) {
  return z.object({ capability: apiCapabilitySchema }).parse(
    await apiRequest(
      `/api/admin/api-capabilities/releases/${encodeURIComponent(releaseId)}/copy-to-draft`,
      { method: "POST", body: { expected_revision: expectedRevision } },
    ),
  ).capability
}
