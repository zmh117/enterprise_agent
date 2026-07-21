import { jsonBody, request } from "@enterprise-agent/api-client";

import type { AgentConfig, AgentPayload, AgentPublication, AgentRevision } from "../domain/models";

export const agentRepository = {
  get: (agentCode: string) => request<{ agent: AgentPayload }>(`/api/admin/agents/${agentCode}`),
  listPublications: (agentCode: string) => request<{ publications: AgentPublication[] }>(`/api/admin/agents/${agentCode}/publications`),
  saveDraft: (agentCode: string, expectedRevision: number, config: AgentConfig) => request<{ revision: AgentRevision }>(`/api/admin/agents/${agentCode}/draft`, { method: "PUT", ...jsonBody({ expected_revision: expectedRevision, config }) }),
  validate: (agentCode: string, revisionId: string) => request<{ revision: AgentRevision }>(`/api/admin/agents/${agentCode}/validate`, { method: "POST", ...jsonBody({ revision_id: revisionId }) }),
  publish: (agentCode: string, revisionId: string) => request<{ publication: AgentPublication }>(`/api/admin/agents/${agentCode}/publish`, { method: "POST", ...jsonBody({ revision_id: revisionId }) }),
  rollback: (agentCode: string, publicationId: string) => request(`/api/admin/agents/${agentCode}/rollback`, { method: "POST", ...jsonBody({ publication_id: publicationId }) }),
};

