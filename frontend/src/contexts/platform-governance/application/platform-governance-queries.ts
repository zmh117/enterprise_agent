import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  createDraftFromRevision,
  createGovernedResource,
  createPlatformSecret,
  deleteGovernedResourceDraft,
  discoverLokiLabelValues,
  disablePlatformSecret,
  getPlatformSecretUsage,
  listBases,
  listEnvironments,
  listGovernedResources,
  listPlatformSecrets,
  listProviderContracts,
  listWorkshops,
  publishGovernedResource,
  rotatePlatformSecret,
  saveGovernedResourceDraft,
  setResourceIdentityStatus,
  setResourceRevisionStatus,
  testLokiResourceDraft,
  verifyGovernedResource,
} from "@/contexts/platform-governance/infrastructure/platform-governance-api"

const secretKey = ["platform-governance", "secrets"] as const
const resourceKey = ["platform-governance", "resources"] as const
const environmentKey = ["platform-governance", "environments"] as const

export function usePlatformSecrets() {
  return useQuery({ queryKey: secretKey, queryFn: listPlatformSecrets })
}

export function useCreatePlatformSecret() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: createPlatformSecret,
    onSuccess: () => client.invalidateQueries({ queryKey: secretKey }),
  })
}

export function useRotatePlatformSecret() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ code, value }: { code: string; value: string }) =>
      rotatePlatformSecret(code, value),
    onSuccess: () => client.invalidateQueries({ queryKey: secretKey }),
  })
}

export function useDisablePlatformSecret() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: disablePlatformSecret,
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: secretKey }),
        client.invalidateQueries({ queryKey: resourceKey }),
      ]),
  })
}

export function usePlatformSecretUsage(code: string) {
  return useQuery({
    queryKey: [...secretKey, code, "usage"],
    queryFn: () => getPlatformSecretUsage(code),
    enabled: Boolean(code),
  })
}

export function useGovernedResources() {
  return useQuery({ queryKey: resourceKey, queryFn: listGovernedResources })
}

export function useResourceFormOptions() {
  return {
    secrets: usePlatformSecrets(),
    environments: useQuery({
      queryKey: environmentKey,
      queryFn: listEnvironments,
    }),
    bases: useQuery({
      queryKey: ["platform-governance", "bases"],
      queryFn: listBases,
    }),
    workshops: useQuery({
      queryKey: ["platform-governance", "workshops"],
      queryFn: listWorkshops,
    }),
    providerContracts: useQuery({
      queryKey: ["platform-governance", "provider-contracts"],
      queryFn: listProviderContracts,
    }),
  }
}

function resourceMutation<TInput, TOutput>(
  mutationFn: (input: TInput) => Promise<TOutput>
) {
  return function useResourceMutation() {
    const client = useQueryClient()
    return useMutation({
      mutationFn,
      onSuccess: () => client.invalidateQueries({ queryKey: resourceKey }),
    })
  }
}

export function useCreateGovernedResource() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: createGovernedResource,
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: resourceKey }),
        client.invalidateQueries({ queryKey: environmentKey }),
      ]),
  })
}

export const useSaveGovernedResourceDraft = resourceMutation(
  ({
    code,
    input,
  }: {
    code: string
    input: Parameters<typeof saveGovernedResourceDraft>[1]
  }) => saveGovernedResourceDraft(code, input)
)
export const useDeleteGovernedResourceDraft = resourceMutation(
  ({ code, expectedRevision }: { code: string; expectedRevision: number }) =>
    deleteGovernedResourceDraft(code, expectedRevision)
)
export const useVerifyGovernedResource = resourceMutation(
  verifyGovernedResource
)
export const usePublishGovernedResource = resourceMutation(
  publishGovernedResource
)
export const useCreateDraftFromRevision = resourceMutation(
  ({ code, revisionId }: { code: string; revisionId: string }) =>
    createDraftFromRevision(code, revisionId)
)
export const useSetResourceRevisionStatus = resourceMutation(
  ({
    code,
    revisionId,
    action,
  }: {
    code: string
    revisionId: string
    action: "disable" | "archive"
  }) => setResourceRevisionStatus(code, revisionId, action)
)
export const useSetResourceIdentityStatus = resourceMutation(
  ({
    code,
    action,
    expectedRevision,
  }: {
    code: string
    action: "disable" | "restore" | "archive"
    expectedRevision: number
  }) => setResourceIdentityStatus(code, action, expectedRevision)
)

export function useTestLokiResourceDraft() {
  return useMutation({ mutationFn: testLokiResourceDraft })
}

export function useDiscoverLokiLabelValues() {
  return useMutation({ mutationFn: discoverLokiLabelValues })
}
