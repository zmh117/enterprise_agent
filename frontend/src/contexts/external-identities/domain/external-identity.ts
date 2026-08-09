import { z } from "zod"

const teamSchema = z.object({ id: z.string(), name: z.string() })

export const selfDingTalkIdentitySchema = z.object({
  provider: z.literal("dingtalk"),
  nickname: z.string(),
  status: z.enum(["enabled", "disabled"]),
  enterprise: z
    .object({ name: z.string(), corp_id: z.string() })
    .nullable(),
  last_used_at: z.string().nullable().optional(),
  staff_id: z.string(),
})

export const selfOnesIdentitySchema = z.object({
  provider: z.literal("ones"),
  user_name: z.string(),
  availability: z.enum([
    "AVAILABLE",
    "REVERIFY_REQUIRED",
    "ADMIN_DISABLED",
    "UNBOUND",
  ]),
  default_team: teamSchema.nullable(),
  verified_at: z.string().nullable().optional(),
  last_success_at: z.string().nullable().optional(),
  user_id: z.string(),
  teams: z.array(teamSchema),
  identity_revision: z.number().int().positive(),
})

export const selfExternalIdentityOverviewSchema = z.object({
  user: z.object({ id: z.string(), display_name: z.string() }),
  dingtalk: z.array(selfDingTalkIdentitySchema),
  ones: selfOnesIdentitySchema.nullable(),
})

export const selfOnesStatusSchema = z.object({
  user: z.object({ id: z.string(), display_name: z.string() }),
  ones: selfOnesIdentitySchema.nullable(),
})

export const onesBindingChallengeSchema = z.object({
  id: z.string(),
  provider: z.literal("ones").default("ones"),
  external_user_id: z.string(),
  display_name: z.string(),
  teams: z.array(teamSchema),
  team_ids: z.array(z.string()),
  expires_at: z.string(),
  status: z.string(),
  created_at: z.string(),
})

export const dingTalkBindingChallengeSchema = z.object({
  id: z.string(),
  code: z.string(),
  expires_at: z.string(),
  status: z.literal("PENDING"),
})

export type SelfDingTalkIdentity = z.infer<
  typeof selfDingTalkIdentitySchema
>
export type SelfOnesIdentity = z.infer<typeof selfOnesIdentitySchema>
export type OnesBindingChallenge = z.infer<typeof onesBindingChallengeSchema>
export type DingTalkBindingChallenge = z.infer<
  typeof dingTalkBindingChallengeSchema
>
