import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type {
  AgentConfig,
  CredentialSource,
  ModelConnectionConfig,
} from "@/contexts/agent-profiles/domain/agent-profile"
import {
  configureModelConnection,
  discoverModelConnection,
  getAgentProfile,
  getModelConnection,
  listAgentPublications,
  listAgentProfiles,
  publishAgentDraft,
  rollbackAgentPublication,
  saveAgentDraft,
  testDraftModelConnection,
  validateAgentDraft,
} from "@/contexts/agent-profiles/infrastructure/agent-profile-api"

export const DEFAULT_AGENT_CODE = "default-diagnostic-agent"
export const DEFAULT_CONNECTION_CODE = "default-deepseek-anthropic"

const agentKey = (agentCode: string) => ["agent-profile", agentCode] as const
const connectionKey = ["model-connection", DEFAULT_CONNECTION_CODE] as const

export function useAgentProfiles() {
  return useQuery({
    queryKey: ["agent-profiles"],
    queryFn: listAgentProfiles,
  })
}

export function useAgentProfile(agentCode = DEFAULT_AGENT_CODE) {
  return useQuery({
    queryKey: agentKey(agentCode),
    queryFn: () => getAgentProfile(agentCode),
  })
}

export function useModelConnection() {
  return useQuery({
    queryKey: connectionKey,
    queryFn: () => getModelConnection(DEFAULT_CONNECTION_CODE),
  })
}

export function useAgentPublications(agentCode = DEFAULT_AGENT_CODE) {
  return useQuery({
    queryKey: [...agentKey(agentCode), "publications"],
    queryFn: () => listAgentPublications(agentCode),
  })
}

function useRefreshAgent(agentCode: string) {
  const client = useQueryClient()
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: agentKey(agentCode) }),
      client.invalidateQueries({
        queryKey: [...agentKey(agentCode), "publications"],
      }),
      client.invalidateQueries({ queryKey: ["agent-profiles"] }),
    ])
}

type CredentialInput = {
  credential_source: CredentialSource
  api_key: string
}

type DraftConnectionInput = CredentialInput & {
  config: Omit<ModelConnectionConfig, "schema_version">
  timeout_seconds?: number
}

export function useDiscoverConnection() {
  return useMutation({
    mutationFn: (
      input: CredentialInput & { base_url: string; timeout_seconds?: number }
    ) => discoverModelConnection(DEFAULT_CONNECTION_CODE, input),
  })
}

export function useTestDraftConnection() {
  return useMutation({
    mutationFn: (input: DraftConnectionInput) =>
      testDraftModelConnection(DEFAULT_CONNECTION_CODE, input),
  })
}

export function useConfigureConnection() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: DraftConnectionInput & { expected_revision: number }) =>
      configureModelConnection(DEFAULT_CONNECTION_CODE, input),
    onSettled: (_data, error) => {
      if (!error || (error instanceof Error && "currentRevision" in error)) {
        return client.invalidateQueries({ queryKey: connectionKey })
      }
      return undefined
    },
  })
}

export function useSaveAgentDraft(agentCode = DEFAULT_AGENT_CODE) {
  const refresh = useRefreshAgent(agentCode)
  return useMutation({
    mutationFn: (input: { expectedRevision: number; config: AgentConfig }) =>
      saveAgentDraft(agentCode, input.expectedRevision, input.config),
    onSuccess: refresh,
  })
}

export function useValidateAgentDraft(agentCode = DEFAULT_AGENT_CODE) {
  const refresh = useRefreshAgent(agentCode)
  return useMutation({
    mutationFn: (revisionId: string) =>
      validateAgentDraft(agentCode, revisionId),
    onSuccess: refresh,
  })
}

export function usePublishAgentDraft(agentCode = DEFAULT_AGENT_CODE) {
  const refresh = useRefreshAgent(agentCode)
  return useMutation({
    mutationFn: (revisionId: string) =>
      publishAgentDraft(agentCode, revisionId),
    onSuccess: refresh,
  })
}

export function useRollbackAgentPublication(agentCode = DEFAULT_AGENT_CODE) {
  const refresh = useRefreshAgent(agentCode)
  return useMutation({
    mutationFn: (publicationId: string) =>
      rollbackAgentPublication(agentCode, publicationId),
    onSuccess: refresh,
  })
}
