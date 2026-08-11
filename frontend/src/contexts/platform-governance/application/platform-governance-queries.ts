import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  createDraftFromRevision,
  createGovernedResource,
  createLokiScopePolicy,
  createPlatformSecret,
  createWorkshopPartitionPolicy,
  copyLokiScopePolicyRevision,
  copyWorkshopPartitionPolicyRevision,
  deleteGovernedResourceDraft,
  discoverLokiLabelValues,
  disablePlatformSecret,
  getPlatformSecretUsage,
  getBuiltinTool,
  getLokiScopePolicy,
  getRuntimeGenerationStatus,
  getWorkshopPartitionPolicy,
  listBases,
  listEnvironments,
  listGovernedResources,
  listBuiltinTools,
  listLokiScopePolicies,
  listPlatformSecrets,
  listWorkshopPartitionPolicies,
  listWorkshops,
  publishGovernedResource,
  publishBuiltinTool,
  publishLokiScopePolicy,
  publishWorkshopPartitionPolicy,
  reconcileBuiltinTools,
  rotatePlatformSecret,
  saveGovernedResourceDraft,
  saveLokiScopePolicyDraft,
  saveWorkshopPartitionPolicyDraft,
  setResourceRevisionStatus,
  setResourceIdentityStatus,
  setBuiltinToolReleaseLifecycle,
  testLokiResourceDraft,
  verifyGovernedResource,
  verifyBuiltinTool,
  verifyLokiScopePolicy,
  verifyWorkshopPartitionPolicy,
} from "@/contexts/platform-governance/infrastructure/platform-governance-api"

const secretKey = ["platform-governance", "secrets"] as const
const resourceKey = ["platform-governance", "resources"] as const
const environmentKey = ["platform-governance", "environments"] as const
const builtinToolKey = ["platform-governance", "builtin-tools"] as const
const workshopPolicyKey = [
  "platform-governance",
  "workshop-partition-policies",
] as const
const lokiPolicyKey = ["platform-governance", "loki-scope-policies"] as const

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

export function useRuntimeGenerationStatus() {
  return useQuery({
    queryKey: ["platform-governance", "runtime-generation"],
    queryFn: getRuntimeGenerationStatus,
  })
}

export function useBuiltinTools() {
  return useQuery({ queryKey: builtinToolKey, queryFn: listBuiltinTools })
}

export function useBuiltinTool(toolIdentifier: string) {
  return useQuery({
    queryKey: [...builtinToolKey, toolIdentifier],
    queryFn: () => getBuiltinTool(toolIdentifier),
    enabled: Boolean(toolIdentifier),
  })
}

function builtinToolMutation<TInput, TOutput>(
  mutationFn: (input: TInput) => Promise<TOutput>
) {
  return function useBuiltinToolMutation() {
    const client = useQueryClient()
    return useMutation({
      mutationFn,
      onSuccess: () => client.invalidateQueries({ queryKey: builtinToolKey }),
    })
  }
}

export const useReconcileBuiltinTools = builtinToolMutation(
  reconcileBuiltinTools
)
export const useVerifyBuiltinTool = builtinToolMutation(
  ({
    toolIdentifier,
    handlerVersion,
  }: {
    toolIdentifier: string
    handlerVersion: string
  }) => verifyBuiltinTool(toolIdentifier, handlerVersion)
)
export const usePublishBuiltinTool = builtinToolMutation(publishBuiltinTool)
export const useSetBuiltinToolReleaseLifecycle = builtinToolMutation(
  setBuiltinToolReleaseLifecycle
)

export function useWorkshopPartitionPolicies() {
  return useQuery({
    queryKey: workshopPolicyKey,
    queryFn: listWorkshopPartitionPolicies,
  })
}

export function useWorkshopPartitionPolicy(code: string) {
  return useQuery({
    queryKey: [...workshopPolicyKey, code],
    queryFn: () => getWorkshopPartitionPolicy(code),
    enabled: Boolean(code),
  })
}

export function useLokiScopePolicies() {
  return useQuery({ queryKey: lokiPolicyKey, queryFn: listLokiScopePolicies })
}

export function useLokiScopePolicy(code: string) {
  return useQuery({
    queryKey: [...lokiPolicyKey, code],
    queryFn: () => getLokiScopePolicy(code),
    enabled: Boolean(code),
  })
}

function policyMutation<TInput, TOutput>(
  policyKey: readonly string[],
  mutationFn: (input: TInput) => Promise<TOutput>
) {
  return function usePolicyMutation() {
    const client = useQueryClient()
    return useMutation({
      mutationFn,
      onSuccess: () =>
        Promise.all([
          client.invalidateQueries({ queryKey: policyKey }),
          client.invalidateQueries({ queryKey: resourceKey }),
        ]),
    })
  }
}

export const useCreateWorkshopPartitionPolicy = policyMutation(
  workshopPolicyKey,
  createWorkshopPartitionPolicy
)
export const useSaveWorkshopPartitionPolicyDraft = policyMutation(
  workshopPolicyKey,
  saveWorkshopPartitionPolicyDraft
)
export const useVerifyWorkshopPartitionPolicy = policyMutation(
  workshopPolicyKey,
  verifyWorkshopPartitionPolicy
)
export const usePublishWorkshopPartitionPolicy = policyMutation(
  workshopPolicyKey,
  publishWorkshopPartitionPolicy
)
export const useCopyWorkshopPartitionPolicyRevision = policyMutation(
  workshopPolicyKey,
  copyWorkshopPartitionPolicyRevision
)
export const useCreateLokiScopePolicy = policyMutation(
  lokiPolicyKey,
  createLokiScopePolicy
)
export const useSaveLokiScopePolicyDraft = policyMutation(
  lokiPolicyKey,
  saveLokiScopePolicyDraft
)
export const useVerifyLokiScopePolicy = policyMutation(
  lokiPolicyKey,
  verifyLokiScopePolicy
)
export const usePublishLokiScopePolicy = policyMutation(
  lokiPolicyKey,
  publishLokiScopePolicy
)
export const useCopyLokiScopePolicyRevision = policyMutation(
  lokiPolicyKey,
  copyLokiScopePolicyRevision
)

export function useTestLokiResourceDraft() {
  return useMutation({ mutationFn: testLokiResourceDraft })
}

export function useDiscoverLokiLabelValues() {
  return useMutation({ mutationFn: discoverLokiLabelValues })
}
