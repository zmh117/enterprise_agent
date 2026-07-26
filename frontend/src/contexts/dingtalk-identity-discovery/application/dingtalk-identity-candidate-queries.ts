import { useEffect } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type {
  BindCandidateInput,
  CandidateListParams,
} from "@/contexts/dingtalk-identity-discovery/domain/dingtalk-identity-candidate"
import {
  bindDingTalkIdentityCandidate,
  countDingTalkIdentityCandidates,
  getDingTalkIdentityCandidate,
  listDingTalkIdentityCandidates,
} from "@/contexts/dingtalk-identity-discovery/infrastructure/dingtalk-identity-candidate-api"
import { externalIdentityKeys } from "@/contexts/external-identities/application/external-identity-queries"

export const dingtalkIdentityCandidateKeys = {
  all: ["dingtalk-identity-candidates"] as const,
  listRoot: () => [...dingtalkIdentityCandidateKeys.all, "list"] as const,
  list: (params: CandidateListParams) =>
    [...dingtalkIdentityCandidateKeys.listRoot(), params] as const,
  count: () => [...dingtalkIdentityCandidateKeys.all, "count"] as const,
  detail: (candidateId: string) =>
    [...dingtalkIdentityCandidateKeys.all, "detail", candidateId] as const,
}

function foregroundInterval(milliseconds: number) {
  return () =>
    typeof document === "undefined" || document.visibilityState === "visible"
      ? milliseconds
      : false
}

function useRefreshWhenVisible(refetch: () => unknown) {
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") refetch()
    }
    document.addEventListener("visibilitychange", refresh)
    return () => document.removeEventListener("visibilitychange", refresh)
  }, [refetch])
}

export function useDingTalkIdentityCandidates(params: CandidateListParams) {
  const query = useQuery({
    queryKey: dingtalkIdentityCandidateKeys.list(params),
    queryFn: () => listDingTalkIdentityCandidates(params),
    retry: false,
    refetchInterval: foregroundInterval(15_000),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  })
  useRefreshWhenVisible(query.refetch)
  return query
}

export function useDingTalkIdentityCandidateCount(enabled = true) {
  const query = useQuery({
    queryKey: dingtalkIdentityCandidateKeys.count(),
    queryFn: countDingTalkIdentityCandidates,
    enabled,
    retry: false,
    refetchInterval: foregroundInterval(30_000),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  })
  useRefreshWhenVisible(query.refetch)
  return query
}

export function useDingTalkIdentityCandidate(candidateId: string) {
  return useQuery({
    queryKey: dingtalkIdentityCandidateKeys.detail(candidateId),
    queryFn: () => getDingTalkIdentityCandidate(candidateId),
    enabled: Boolean(candidateId),
    retry: false,
  })
}

export function useBindDingTalkIdentityCandidate(
  candidateId: string,
  userId: string
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: BindCandidateInput) =>
      bindDingTalkIdentityCandidate(candidateId, input),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: dingtalkIdentityCandidateKeys.all,
        }),
        queryClient.invalidateQueries({
          queryKey: externalIdentityKeys.user(userId),
        }),
      ])
    },
  })
}
