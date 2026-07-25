import { z } from "zod"

import {
  agentDetailSchema,
  agentPublicationSchema,
  agentRevisionSchema,
  agentSummarySchema,
  modelConnectionRevisionSchema,
  modelConnectionSchema,
  type AgentConfig,
  type ModelConnectionConfig,
} from "@/contexts/agent-profiles/domain/agent-profile"
import { apiRequest } from "@/shared/api/api-client"

export async function listAgentProfiles() {
  return z
    .object({ agents: z.array(agentSummarySchema) })
    .parse(await apiRequest("/api/admin/agents")).agents
}

export async function getAgentProfile(code: string) {
  return z
    .object({ agent: agentDetailSchema })
    .parse(await apiRequest(`/api/admin/agents/${encodeURIComponent(code)}`))
    .agent
}

export async function getModelConnection(code: string) {
  return z
    .object({ connection: modelConnectionSchema })
    .parse(
      await apiRequest(
        `/api/admin/model-connections/${encodeURIComponent(code)}`
      )
    ).connection
}

export async function saveModelConnection(
  code: string,
  input: {
    expected_revision: number
    config: Omit<ModelConnectionConfig, "schema_version">
  }
) {
  return z
    .object({ revision: modelConnectionRevisionSchema })
    .parse(
      await apiRequest(
        `/api/admin/model-connections/${encodeURIComponent(code)}/revision`,
        { method: "PUT", body: input }
      )
    ).revision
}

export async function rotateModelCredential(
  code: string,
  input: { expected_revision: number; api_key: string }
) {
  return z
    .object({ revision: modelConnectionRevisionSchema })
    .parse(
      await apiRequest(
        `/api/admin/model-connections/${encodeURIComponent(code)}/credential`,
        { method: "PUT", body: input }
      )
    ).revision
}

export async function testModelConnection(code: string, revisionId: string) {
  return z
    .object({
      result: z.object({
        success: z.boolean(),
        connection_revision_id: z.string(),
        provider_host: z.string(),
        model: z.string(),
        duration_ms: z.number(),
        runtime: z.string(),
        detail: z.string(),
      }),
    })
    .parse(
      await apiRequest(
        `/api/admin/model-connections/${encodeURIComponent(code)}/test`,
        {
          method: "POST",
          body: { revision_id: revisionId, timeout_seconds: 15 },
        }
      )
    ).result
}

export async function saveAgentDraft(
  code: string,
  expectedRevision: number,
  config: AgentConfig
) {
  return z.object({ revision: agentRevisionSchema }).parse(
    await apiRequest(`/api/admin/agents/${encodeURIComponent(code)}/draft`, {
      method: "PUT",
      body: { expected_revision: expectedRevision, config },
    })
  ).revision
}

export async function validateAgentDraft(code: string, revisionId: string) {
  return z
    .object({ revision: agentRevisionSchema })
    .parse(
      await apiRequest(
        `/api/admin/agents/${encodeURIComponent(code)}/validate`,
        { method: "POST", body: { revision_id: revisionId } }
      )
    ).revision
}

export async function publishAgentDraft(code: string, revisionId: string) {
  return z
    .object({ publication: agentPublicationSchema })
    .parse(
      await apiRequest(
        `/api/admin/agents/${encodeURIComponent(code)}/publish`,
        { method: "POST", body: { revision_id: revisionId } }
      )
    ).publication
}

export async function listAgentPublications(code: string) {
  return z
    .object({ publications: z.array(agentPublicationSchema) })
    .parse(
      await apiRequest(
        `/api/admin/agents/${encodeURIComponent(code)}/publications`
      )
    ).publications
}

export async function rollbackAgentPublication(
  code: string,
  publicationId: string
) {
  return z
    .object({ publication: agentPublicationSchema })
    .parse(
      await apiRequest(
        `/api/admin/agents/${encodeURIComponent(code)}/rollback`,
        { method: "POST", body: { publication_id: publicationId } }
      )
    ).publication
}
