import { z } from "zod"

import {
  agentDetailSchema,
  agentPublicationSchema,
  agentRevisionSchema,
  agentSummarySchema,
  modelDiscoveryResultSchema,
  modelDraftTestResultSchema,
  modelConnectionRevisionSchema,
  modelConnectionSchema,
  type AgentConfig,
  type CredentialSource,
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

type CredentialInput = {
  credential_source: CredentialSource
  api_key: string
}

type DraftConnectionInput = CredentialInput & {
  config: Omit<ModelConnectionConfig, "schema_version">
  timeout_seconds?: number
}

export async function discoverModelConnection(
  code: string,
  input: CredentialInput & { base_url: string; timeout_seconds?: number }
) {
  return z
    .object({ result: modelDiscoveryResultSchema })
    .parse(
      await apiRequest(
        `/api/admin/model-connections/${encodeURIComponent(code)}/discover`,
        { method: "POST", body: input }
      )
    ).result
}

export async function testDraftModelConnection(
  code: string,
  input: DraftConnectionInput
) {
  return z
    .object({ result: modelDraftTestResultSchema })
    .parse(
      await apiRequest(
        `/api/admin/model-connections/${encodeURIComponent(code)}/test-draft`,
        { method: "POST", body: input }
      )
    ).result
}

export async function configureModelConnection(
  code: string,
  input: DraftConnectionInput & { expected_revision: number }
) {
  return z.object({ revision: modelConnectionRevisionSchema }).parse(
    await apiRequest(
      `/api/admin/model-connections/${encodeURIComponent(code)}/configure`,
      {
        method: "PUT",
        body: input,
      }
    )
  ).revision
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
