import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  beginSelfDingTalkBinding,
  beginSelfOnesBinding,
  changeSelfOnesDefaultTeam,
  confirmSelfOnesBinding,
  getSelfExternalIdentities,
  unbindSelfOnesBinding,
} from "@/contexts/external-identities/infrastructure/external-identity-api"

const selfIdentityKey = ["external-identities", "self"] as const

export function useSelfExternalIdentities() {
  return useQuery({
    queryKey: selfIdentityKey,
    queryFn: getSelfExternalIdentities,
    retry: false,
  })
}

export function useBeginSelfOnesBinding() {
  return useMutation({ mutationFn: beginSelfOnesBinding })
}

export function useConfirmSelfOnesBinding() {
  return useRefreshingMutation(confirmSelfOnesBinding)
}

export function useChangeSelfOnesDefaultTeam() {
  return useRefreshingMutation(changeSelfOnesDefaultTeam)
}

export function useUnbindSelfOnesBinding() {
  return useRefreshingMutation(unbindSelfOnesBinding)
}

export function useBeginSelfDingTalkBinding() {
  return useMutation({ mutationFn: beginSelfDingTalkBinding })
}

function useRefreshingMutation<TInput, TResult>(
  mutationFn: (input: TInput) => Promise<TResult>
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => client.invalidateQueries({ queryKey: selfIdentityKey }),
  })
}
