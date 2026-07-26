import { z } from "zod"

import {
  dingtalkIdentityCandidateSchema,
  type BindCandidateInput,
  type CandidateListParams,
} from "@/contexts/dingtalk-identity-discovery/domain/dingtalk-identity-candidate"
import { apiRequest } from "@/shared/api/api-client"

const listResponseSchema = z.object({
  candidates: z.array(dingtalkIdentityCandidateSchema),
  next_cursor: z.string(),
  has_more: z.boolean(),
})

const countResponseSchema = z.object({
  count: z.number().int().nonnegative(),
})

const detailResponseSchema = z.object({
  candidate: dingtalkIdentityCandidateSchema,
})

export async function listDingTalkIdentityCandidates(
  params: CandidateListParams
) {
  const query = new URLSearchParams({
    search: params.search,
    conversation_scope: params.conversationScope,
    cursor: params.cursor,
    limit: String(params.limit),
  })
  return listResponseSchema.parse(
    await apiRequest(
      `/api/admin/dingtalk-identity-candidates?${query.toString()}`
    )
  )
}

export async function countDingTalkIdentityCandidates() {
  return countResponseSchema.parse(
    await apiRequest("/api/admin/dingtalk-identity-candidates/count")
  ).count
}

export async function getDingTalkIdentityCandidate(candidateId: string) {
  return detailResponseSchema.parse(
    await apiRequest(
      `/api/admin/dingtalk-identity-candidates/${encodeURIComponent(candidateId)}`
    )
  ).candidate
}

export async function bindDingTalkIdentityCandidate(
  candidateId: string,
  input: BindCandidateInput
) {
  return apiRequest(
    `/api/admin/dingtalk-identity-candidates/${encodeURIComponent(candidateId)}/bind`,
    {
      method: "POST",
      body: input,
    }
  )
}
