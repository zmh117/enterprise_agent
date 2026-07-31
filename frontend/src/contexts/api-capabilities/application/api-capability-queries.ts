import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  copyCapabilityRelease,
  createApiConnection,
  initializeOnesSearch,
  listApiCapabilities,
  listApiConnections,
  publishApiCapability,
  publishApiConnection,
  saveApiCapabilityDraft,
  saveApiConnectionDraft,
  testApiCapability,
  updateApiConnectionRevision,
  updateCapabilityRelease,
  verifyApiCapability,
  verifyApiConnection,
} from "@/contexts/api-capabilities/infrastructure/api-capability-api"

const connectionKey = ["api-capability-governance", "connections"] as const
const capabilityKey = ["api-capability-governance", "capabilities"] as const

export function useApiConnections() {
  return useQuery({ queryKey: connectionKey, queryFn: listApiConnections, retry: false })
}

export function useApiCapabilities() {
  return useQuery({ queryKey: capabilityKey, queryFn: listApiCapabilities, retry: false })
}

function useGovernanceMutation<TInput, TResult>(
  mutationFn: (input: TInput) => Promise<TResult>,
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: connectionKey }),
        client.invalidateQueries({ queryKey: capabilityKey }),
      ]),
  })
}

export function useCreateApiConnection() {
  return useGovernanceMutation(createApiConnection)
}

export function useSaveApiConnectionDraft(connectionId: string) {
  return useGovernanceMutation(
    (input: Parameters<typeof saveApiConnectionDraft>[1]) =>
      saveApiConnectionDraft(connectionId, input),
  )
}

export function useVerifyApiConnection(connectionId: string) {
  return useGovernanceMutation(
    (input: Parameters<typeof verifyApiConnection>[1]) =>
      verifyApiConnection(connectionId, input),
  )
}

export function usePublishApiConnection(connectionId: string) {
  return useGovernanceMutation(
    (input: Parameters<typeof publishApiConnection>[1]) =>
      publishApiConnection(connectionId, input),
  )
}

export function useUpdateApiConnectionRevision() {
  return useGovernanceMutation(
    (input: {
      revisionId: string
      status: "PUBLISHED" | "DISABLED" | "ARCHIVED"
    }) => updateApiConnectionRevision(input.revisionId, input.status),
  )
}

export function useInitializeOnesSearch() {
  return useGovernanceMutation(initializeOnesSearch)
}

export function useSaveApiCapabilityDraft(capabilityId: string) {
  return useGovernanceMutation(
    (input: Parameters<typeof saveApiCapabilityDraft>[1]) =>
      saveApiCapabilityDraft(capabilityId, input),
  )
}

export function useTestApiCapability(capabilityId: string) {
  return useGovernanceMutation(
    (input: Parameters<typeof testApiCapability>[1]) =>
      testApiCapability(capabilityId, input),
  )
}

export function useVerifyApiCapability(capabilityId: string) {
  return useGovernanceMutation(
    (input: Parameters<typeof verifyApiCapability>[1]) =>
      verifyApiCapability(capabilityId, input),
  )
}

export function usePublishApiCapability(capabilityId: string) {
  return useGovernanceMutation(
    (input: Parameters<typeof publishApiCapability>[1]) =>
      publishApiCapability(capabilityId, input),
  )
}

export function useUpdateCapabilityRelease() {
  return useGovernanceMutation(
    (input: {
      releaseId: string
      status: "ACTIVE" | "DEPRECATED" | "DISABLED" | "ARCHIVED"
      reason: string
      replacement_release_id: string
    }) => updateCapabilityRelease(input.releaseId, input),
  )
}

export function useCopyCapabilityRelease() {
  return useGovernanceMutation(
    (input: { releaseId: string; expectedRevision: number }) =>
      copyCapabilityRelease(input.releaseId, input.expectedRevision),
  )
}
