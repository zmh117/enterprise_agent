import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type {
  AgentConfig,
  ModelConnectionConfig,
} from "@/contexts/agent-profiles/domain/agent-profile"
import {
  getAgentProfile,
  getModelConnection,
  listAgentPublications,
  listAgentProfiles,
  publishAgentDraft,
  rotateModelCredential,
  rollbackAgentPublication,
  saveAgentDraft,
  saveModelConnection,
  testModelConnection,
  validateAgentDraft,
} from "@/contexts/agent-profiles/infrastructure/agent-profile-api"

export const DEFAULT_AGENT_CODE = "default-diagnostic-agent"
export const DEFAULT_CONNECTION_CODE = "default-deepseek-anthropic"

const agentKey = ["agent-profile", DEFAULT_AGENT_CODE] as const
const connectionKey = ["model-connection", DEFAULT_CONNECTION_CODE] as const

export function useAgentProfiles() {
  return useQuery({
    queryKey: ["agent-profiles"],
    queryFn: listAgentProfiles,
  })
}

export function useAgentProfile() {
  return useQuery({
    queryKey: agentKey,
    queryFn: () => getAgentProfile(DEFAULT_AGENT_CODE),
  })
}

export function useModelConnection() {
  return useQuery({
    queryKey: connectionKey,
    queryFn: () => getModelConnection(DEFAULT_CONNECTION_CODE),
  })
}

export function useAgentPublications() {
  return useQuery({
    queryKey: [...agentKey, "publications"],
    queryFn: () => listAgentPublications(DEFAULT_AGENT_CODE),
  })
}

function useRefreshAgent() {
  const client = useQueryClient()
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: agentKey }),
      client.invalidateQueries({ queryKey: [...agentKey, "publications"] }),
    ])
}

export function useSaveConnection() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: {
      expected_revision: number
      config: Omit<ModelConnectionConfig, "schema_version">
    }) => saveModelConnection(DEFAULT_CONNECTION_CODE, input),
    onSuccess: () => client.invalidateQueries({ queryKey: connectionKey }),
  })
}

export function useRotateCredential() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { expected_revision: number; api_key: string }) =>
      rotateModelCredential(DEFAULT_CONNECTION_CODE, input),
    onSuccess: () => client.invalidateQueries({ queryKey: connectionKey }),
  })
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (revisionId: string) =>
      testModelConnection(DEFAULT_CONNECTION_CODE, revisionId),
  })
}

export function useSaveAgentDraft() {
  const refresh = useRefreshAgent()
  return useMutation({
    mutationFn: (input: { expectedRevision: number; config: AgentConfig }) =>
      saveAgentDraft(DEFAULT_AGENT_CODE, input.expectedRevision, input.config),
    onSuccess: refresh,
  })
}

export function useValidateAgentDraft() {
  const refresh = useRefreshAgent()
  return useMutation({
    mutationFn: (revisionId: string) =>
      validateAgentDraft(DEFAULT_AGENT_CODE, revisionId),
    onSuccess: refresh,
  })
}

export function usePublishAgentDraft() {
  const refresh = useRefreshAgent()
  return useMutation({
    mutationFn: (revisionId: string) =>
      publishAgentDraft(DEFAULT_AGENT_CODE, revisionId),
    onSuccess: refresh,
  })
}

export function useRollbackAgentPublication() {
  const refresh = useRefreshAgent()
  return useMutation({
    mutationFn: (publicationId: string) =>
      rollbackAgentPublication(DEFAULT_AGENT_CODE, publicationId),
    onSuccess: refresh,
  })
}
