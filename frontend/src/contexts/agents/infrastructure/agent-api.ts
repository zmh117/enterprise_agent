import type {
  AgentDetail,
  AgentDraftConfig,
  AgentListResponse,
  AgentPublication,
  AgentRevision,
  LifecycleStatus,
  ModelConnectionConfig,
  ModelConnectionDetail,
} from "@/contexts/agents/domain/agent"
import { apiRequest, createIdempotencyKey } from "@/shared/api/api-client"

const root = "/api/admin/agents"

function writeHeaders(scope: string) {
  return { "Idempotency-Key": createIdempotencyKey(scope) }
}

export function listAgents() {
  return apiRequest<AgentListResponse>(root)
}

export async function getAgent(agentCode: string) {
  const response = await apiRequest<{ agent: AgentDetail }>(
    `${root}/${encodeURIComponent(agentCode)}`
  )
  return response.agent
}

export async function createAgent(input: {
  code: string
  name: string
  description: string
  project_code: string
}) {
  const response = await apiRequest<{ agent: AgentDetail }>(root, {
    method: "POST",
    headers: writeHeaders("agent-create"),
    body: { expected_revision: 0, ...input },
  })
  return response.agent
}

export async function updateAgent(
  agentCode: string,
  input: {
    expectedRevision: number
    name: string
    description: string
    project_code: string
    status: LifecycleStatus
  }
) {
  const { expectedRevision, ...value } = input
  const response = await apiRequest<{ agent: AgentDetail }>(
    `${root}/${encodeURIComponent(agentCode)}`,
    {
      method: "PUT",
      headers: writeHeaders("agent-update"),
      body: { expected_revision: expectedRevision, ...value },
    }
  )
  return response.agent
}

export async function saveAgentDraft(
  agentCode: string,
  expectedRevision: number,
  config: AgentDraftConfig
) {
  const response = await apiRequest<{ revision: AgentRevision }>(
    `${root}/${encodeURIComponent(agentCode)}/draft`,
    {
      method: "PUT",
      headers: writeHeaders("agent-draft"),
      body: { expected_revision: expectedRevision, config },
    }
  )
  return response.revision
}

export async function validateAgent(
  agentCode: string,
  revisionId: string,
  expectedRevision: number
) {
  const response = await apiRequest<{ revision: AgentRevision }>(
    `${root}/${encodeURIComponent(agentCode)}/validate`,
    {
      method: "POST",
      headers: writeHeaders("agent-validate"),
      body: {
        revision_id: revisionId,
        expected_revision: expectedRevision,
      },
    }
  )
  return response.revision
}

export async function publishAgent(
  agentCode: string,
  revisionId: string,
  expectedRevision: number
) {
  const response = await apiRequest<{ publication: AgentPublication }>(
    `${root}/${encodeURIComponent(agentCode)}/publish`,
    {
      method: "POST",
      headers: writeHeaders("agent-publish"),
      body: {
        revision_id: revisionId,
        expected_revision: expectedRevision,
      },
    }
  )
  return response.publication
}

export async function rollbackAgent(
  agentCode: string,
  publicationId: string,
  expectedRevision: number
) {
  const response = await apiRequest<{ publication: AgentPublication }>(
    `${root}/${encodeURIComponent(agentCode)}/rollback`,
    {
      method: "POST",
      headers: writeHeaders("agent-rollback"),
      body: {
        publication_id: publicationId,
        expected_revision: expectedRevision,
      },
    }
  )
  return response.publication
}

export async function listAgentPublications(agentCode: string) {
  const response = await apiRequest<{ publications: AgentPublication[] }>(
    `${root}/${encodeURIComponent(agentCode)}/publications`
  )
  return response.publications
}

export async function getModelConnection(code: string) {
  const response = await apiRequest<{ connection: ModelConnectionDetail }>(
    `/api/admin/model-connections/${encodeURIComponent(code)}`
  )
  return response.connection
}

export async function saveModelConnectionRevision(
  code: string,
  expectedRevision: number,
  config: ModelConnectionConfig
) {
  const response = await apiRequest<{ revision: unknown }>(
    `/api/admin/model-connections/${encodeURIComponent(code)}/revision`,
    {
      method: "PUT",
      headers: writeHeaders("model-revision"),
      body: { expected_revision: expectedRevision, config },
    }
  )
  return response.revision
}

export async function rotateModelCredential(
  code: string,
  expectedRevision: number,
  apiKey: string
) {
  const response = await apiRequest<{ revision: unknown }>(
    `/api/admin/model-connections/${encodeURIComponent(code)}/credential`,
    {
      method: "POST",
      headers: writeHeaders("model-credential"),
      body: { expected_revision: expectedRevision, api_key: apiKey },
    }
  )
  return response.revision
}

export async function testModelConnection(
  code: string,
  revisionId: string,
  expectedRevision: number
) {
  const response = await apiRequest<{ result: Record<string, unknown> }>(
    `/api/admin/model-connections/${encodeURIComponent(code)}/revisions/${encodeURIComponent(revisionId)}/test`,
    {
      method: "POST",
      headers: writeHeaders("model-test"),
      body: { expected_revision: expectedRevision, timeout_seconds: 15 },
    }
  )
  return response.result
}
