import { z } from "zod"

export const conversationScopeSchema = z.enum(["direct", "group", "both"])
export const candidateIdentityStateSchema = z.enum([
  "waiting_bind",
  "restore_required",
])

export const candidateMessageSchema = z.object({
  id: z.string(),
  connector_id: z.string(),
  connector_name: z.string(),
  robot_code: z.string(),
  conversation_type: z.enum(["direct", "group"]),
  conversation_id: z.string(),
  message_kind: z.string(),
  safe_text: z.string(),
  text_truncated: z.boolean(),
  attachment_type: z.string(),
  attachment_name: z.string(),
  attachment_size: z.number().int().nonnegative().nullable(),
  occurred_at: z.string(),
  received_at: z.string(),
})

export const historicalIdentitySchema = z.object({
  id: z.string(),
  status: z.string(),
  revision: z.number().int().positive(),
  user_id: z.string(),
  username: z.string(),
  user_display_name: z.string(),
  user_status: z.string(),
})

export const dingtalkIdentityCandidateSchema = z.object({
  id: z.string(),
  dingtalk_enterprise_id: z.string(),
  enterprise_name: z.string(),
  corp_id: z.string(),
  external_subject_id: z.string(),
  display_name: z.string(),
  first_seen_at: z.string(),
  last_seen_at: z.string(),
  observation_count: z.number().int().nonnegative(),
  revision: z.number().int().positive(),
  identity_state: candidateIdentityStateSchema,
  conversation_scope: conversationScopeSchema,
  group_ids: z.array(z.string()),
  robot_codes: z.array(z.string()),
  connector_names: z.array(z.string()),
  latest_message: candidateMessageSchema.nullable(),
  messages: z.array(candidateMessageSchema),
  historical_identity: historicalIdentitySchema.nullable(),
})

export type ConversationScope = z.infer<typeof conversationScopeSchema>
export type DingTalkIdentityCandidate = z.infer<
  typeof dingtalkIdentityCandidateSchema
>

export type CandidateListParams = {
  search: string
  conversationScope: "all" | ConversationScope
  cursor: string
  limit: number
}

export type BindCandidateInput = {
  target_user_id: string
  expected_candidate_revision: number
  expected_user_revision: number
  initial_role_ids: string[]
  bind_without_access_confirmed: boolean
  replace_current_confirmed: boolean
}
