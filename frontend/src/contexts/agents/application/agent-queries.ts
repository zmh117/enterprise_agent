import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type { AgentDraftConfig } from "@/contexts/agents/domain/agent"
import {
  getAgent,
  getModelConnection,
  listAgentPublications,
  listAgents,
  publishAgent,
  rollbackAgent,
  rotateModelCredential,
  saveAgentDraft,
  saveModelConnectionRevision,
  testModelConnection,
  updateAgent,
  validateAgent,
} from "@/contexts/agents/infrastructure/agent-api"

export const agentKeys = {
  all: ["admin", "agents"] as const,
  detail: (code: string) => ["admin", "agents", code] as const,
  publications: (code: string) =>
    ["admin", "agents", code, "publications"] as const,
  model: (code: string) => ["admin", "model-connections", code] as const,
}

export function useAgents() {
  return useQuery({ queryKey: agentKeys.all, queryFn: listAgents })
}

export function useAgent(code: string) {
  return useQuery({
    queryKey: agentKeys.detail(code),
    queryFn: () => getAgent(code),
    enabled: Boolean(code),
  })
}

export function useAgentPublications(code: string) {
  return useQuery({
    queryKey: agentKeys.publications(code),
    queryFn: () => listAgentPublications(code),
    enabled: Boolean(code),
  })
}

export function useAgentActions(code: string) {
  const client = useQueryClient()
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: agentKeys.all }),
      client.invalidateQueries({ queryKey: agentKeys.detail(code) }),
      client.invalidateQueries({ queryKey: agentKeys.publications(code) }),
    ])
  }
  return {
    update: useMutation({
      mutationFn: (input: Parameters<typeof updateAgent>[1]) =>
        updateAgent(code, input),
      onSuccess: refresh,
    }),
    saveDraft: useMutation({
      mutationFn: (input: {
        expectedRevision: number
        config: AgentDraftConfig
      }) => saveAgentDraft(code, input.expectedRevision, input.config),
      onSuccess: refresh,
    }),
    validate: useMutation({
      mutationFn: (input: { revisionId: string; expectedRevision: number }) =>
        validateAgent(code, input.revisionId, input.expectedRevision),
      onSuccess: refresh,
    }),
    publish: useMutation({
      mutationFn: (input: { revisionId: string; expectedRevision: number }) =>
        publishAgent(code, input.revisionId, input.expectedRevision),
      onSuccess: refresh,
    }),
    rollback: useMutation({
      mutationFn: (input: {
        publicationId: string
        expectedRevision: number
      }) => rollbackAgent(code, input.publicationId, input.expectedRevision),
      onSuccess: refresh,
    }),
  }
}

export function useModelConnection(code: string) {
  return useQuery({
    queryKey: agentKeys.model(code),
    queryFn: () => getModelConnection(code),
    enabled: Boolean(code),
  })
}

export function useModelConnectionActions(code: string) {
  const client = useQueryClient()
  const refresh = () =>
    client.invalidateQueries({ queryKey: agentKeys.model(code) })
  return {
    save: useMutation({
      mutationFn: (input: Parameters<typeof saveModelConnectionRevision>) =>
        saveModelConnectionRevision(...input),
      onSuccess: refresh,
    }),
    rotate: useMutation({
      mutationFn: (input: Parameters<typeof rotateModelCredential>) =>
        rotateModelCredential(...input),
      onSuccess: refresh,
    }),
    test: useMutation({
      mutationFn: (input: Parameters<typeof testModelConnection>) =>
        testModelConnection(...input),
      onSuccess: refresh,
    }),
  }
}
