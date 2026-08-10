import { apiRequest, createIdempotencyKey } from "@/shared/api/api-client"

export type CandidateMessage = {
  id: string
  connector_name: string
  conversation_type: "direct" | "group"
  conversation_id: string
  message_kind: string
  safe_text: string
  text_truncated: boolean
  attachment_type: string
  attachment_name: string
  occurred_at: string
  received_at: string
}

export type DingTalkIdentityCandidate = {
  id: string
  dingtalk_enterprise_id: string
  enterprise_name: string
  corp_id: string
  external_subject_id: string
  display_name: string
  first_seen_at: string
  last_seen_at: string
  observation_count: number
  revision: number
  identity_state: "waiting_bind" | "restore_required"
  conversation_scope: "direct" | "group" | "both"
  group_ids: string[]
  robot_codes: string[]
  connector_names: string[]
  latest_message: CandidateMessage | null
  messages: CandidateMessage[]
  historical_identity: null | {
    id: string
    status: string
    revision: number
    user_id: string
    username: string
    user_display_name: string
    user_status: string
  }
}

export async function listIdentityCandidates(input: {
  search: string
  conversationScope: string
}) {
  const query = new URLSearchParams({
    search: input.search,
    conversation_scope: input.conversationScope,
    limit: "100",
  })
  return apiRequest<{
    candidates: DingTalkIdentityCandidate[]
    next_cursor: string
    has_more: boolean
  }>(`/api/admin/dingtalk-identity-candidates?${query.toString()}`)
}

export async function bindIdentityCandidate(input: {
  candidateId: string
  targetUserId: string
  expectedCandidateRevision: number
  expectedUserRevision: number
  initialRoleIds: string[]
  bindWithoutAccessConfirmed: boolean
}) {
  return apiRequest<Record<string, unknown>>(
    `/api/admin/dingtalk-identity-candidates/${encodeURIComponent(input.candidateId)}/bind`,
    {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("identity-bind") },
      body: {
        target_user_id: input.targetUserId,
        expected_candidate_revision: input.expectedCandidateRevision,
        expected_user_revision: input.expectedUserRevision,
        initial_role_ids: input.initialRoleIds,
        bind_without_access_confirmed: input.bindWithoutAccessConfirmed,
        replace_current_confirmed: false,
      },
    }
  )
}
