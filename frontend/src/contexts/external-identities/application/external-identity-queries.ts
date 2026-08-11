import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  beginSelfOnesIdentity,
  confirmSelfOnesIdentity,
  getSelfExternalIdentities,
  getSelfOnesIdentity,
  listExternalIdentities,
  listIdentityProviders,
  unbindIdentity,
  updateIdentityStatus,
  unbindSelfOnesIdentity,
} from "@/contexts/external-identities/infrastructure/external-identity-api"

export const externalIdentityKeys = {
  all: ["external-identities"] as const,
  providers: () => [...externalIdentityKeys.all, "providers"] as const,
  user: (userId: string) =>
    [...externalIdentityKeys.all, "user", userId] as const,
  self: () => [...externalIdentityKeys.all, "self"] as const,
  selfOnes: () => [...externalIdentityKeys.all, "self", "ones"] as const,
}

export function useExternalIdentities(userId: string) {
  return useQuery({
    queryKey: externalIdentityKeys.user(userId),
    queryFn: () => listExternalIdentities(userId),
    enabled: Boolean(userId),
    retry: false,
  })
}

export function useIdentityProviders() {
  return useQuery({
    queryKey: externalIdentityKeys.providers(),
    queryFn: listIdentityProviders,
    retry: false,
  })
}

export function useUpdateIdentityStatus(userId: string) {
  return useIdentityMutation(
    userId,
    (input: {
      identityId: string
      expectedRevision: number
      status: "enabled" | "disabled"
    }) =>
      updateIdentityStatus(input.identityId, {
        expected_revision: input.expectedRevision,
        status: input.status,
      })
  )
}

export function useUnbindIdentity(userId: string) {
  return useIdentityMutation(
    userId,
    (input: { identityId: string; expectedRevision: number }) =>
      unbindIdentity(input.identityId, input.expectedRevision)
  )
}

export function useSelfExternalIdentities() {
  return useQuery({
    queryKey: externalIdentityKeys.self(),
    queryFn: getSelfExternalIdentities,
    retry: false,
  })
}

export function useSelfOnesIdentity() {
  return useQuery({
    queryKey: externalIdentityKeys.selfOnes(),
    queryFn: getSelfOnesIdentity,
    retry: false,
  })
}

export function useBeginSelfOnesIdentity() {
  return useMutation({ mutationFn: beginSelfOnesIdentity })
}

export function useConfirmSelfOnesIdentity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: confirmSelfOnesIdentity,
    onSuccess: () => Promise.all([
      queryClient.invalidateQueries({ queryKey: externalIdentityKeys.self() }),
      queryClient.invalidateQueries({ queryKey: externalIdentityKeys.selfOnes() }),
    ]),
  })
}

export function useUnbindSelfOnesIdentity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: unbindSelfOnesIdentity,
    onSuccess: () => Promise.all([
      queryClient.invalidateQueries({ queryKey: externalIdentityKeys.self() }),
      queryClient.invalidateQueries({ queryKey: externalIdentityKeys.selfOnes() }),
    ]),
  })
}

function useIdentityMutation<TInput, TResult>(
  userId: string,
  mutationFn: (input: TInput) => Promise<TResult>
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: externalIdentityKeys.user(userId),
      })
    },
  })
}
