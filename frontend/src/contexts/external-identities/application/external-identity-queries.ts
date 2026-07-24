import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type {
  BindDingTalkInput,
  BindOnesInput,
} from "@/contexts/external-identities/domain/external-identity"
import {
  bindDingTalkIdentity,
  bindOnesIdentity,
  listDingTalkTenants,
  listExternalIdentities,
  listIdentityProviders,
  unbindIdentity,
  updateIdentityStatus,
} from "@/contexts/external-identities/infrastructure/external-identity-api"

export const externalIdentityKeys = {
  all: ["external-identities"] as const,
  providers: () => [...externalIdentityKeys.all, "providers"] as const,
  tenants: () => [...externalIdentityKeys.all, "dingtalk-tenants"] as const,
  user: (userId: string) =>
    [...externalIdentityKeys.all, "user", userId] as const,
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

export function useDingTalkTenants() {
  return useQuery({
    queryKey: externalIdentityKeys.tenants(),
    queryFn: listDingTalkTenants,
    retry: false,
  })
}

export function useBindDingTalkIdentity(userId: string) {
  return useIdentityMutation(userId, (input: BindDingTalkInput) =>
    bindDingTalkIdentity(userId, input),
  )
}

export async function verifyAndBindOnesIdentity(
  userId: string,
  input: BindOnesInput,
) {
  return bindOnesIdentity(userId, input)
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
      }),
  )
}

export function useUnbindIdentity(userId: string) {
  return useIdentityMutation(
    userId,
    (input: { identityId: string; expectedRevision: number }) =>
      unbindIdentity(input.identityId, input.expectedRevision),
  )
}

function useIdentityMutation<TInput, TResult>(
  userId: string,
  mutationFn: (input: TInput) => Promise<TResult>,
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
