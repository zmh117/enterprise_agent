import { z } from "zod"

export const externalIdentityProviderSchema = z.enum(["dingtalk", "ones"])
export const externalIdentityStatusSchema = z.enum([
  "enabled",
  "disabled",
  "unbound",
])

const teamSchema = z.object({ id: z.string(), name: z.string() })
const dingtalkEnterpriseSchema = z.object({
  name: z.string(),
  corp_id: z.string(),
})

export const selfDingTalkIdentitySchema = z.object({
  provider: z.literal("dingtalk"),
  nickname: z.string(),
  status: z.enum(["enabled", "disabled"]),
  enterprise: dingtalkEnterpriseSchema.nullable(),
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
})

const dingtalkObservationSchema = z.object({
  application_name: z.string(),
  first_observed_at: z.string().nullable().optional(),
  last_observed_at: z.string().nullable().optional(),
})

export const adminDingTalkIdentitySchema = selfDingTalkIdentitySchema.extend({
  status: externalIdentityStatusSchema,
  identity_id: z.string(),
  revision: z.number().int().positive(),
  binding_confirmed_at: z.string().nullable().optional(),
  observations: z.array(dingtalkObservationSchema),
})

export const adminOnesIdentitySchema = selfOnesIdentitySchema.extend({
  identity_id: z.string(),
  identity_status: externalIdentityStatusSchema,
  identity_revision: z.number().int().positive(),
})

export const adminExternalIdentitySchema = z.discriminatedUnion("provider", [
  adminDingTalkIdentitySchema,
  adminOnesIdentitySchema,
])

export const adminExternalIdentityOverviewSchema = z.object({
  user_id: z.string(),
  current: z.array(adminExternalIdentitySchema),
  history: z.array(adminExternalIdentitySchema),
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

export const credentialTechnicalSchema = z.object({
  status: z.enum(["ACTIVE", "INVALID", "DISABLED"]),
  revision: z.number().int().positive(),
  last_attempt_at: z.string().nullable().optional(),
  last_success_at: z.string().nullable().optional(),
  last_error_code: z.string(),
  last_error_at: z.string().nullable().optional(),
})

export const connectionTechnicalSchema = z.object({
  name: z.string(),
  revision: z.number().int().positive(),
  status: z.string(),
})

export const adminOnesTechnicalSchema = adminOnesIdentitySchema.extend({
  credential: credentialTechnicalSchema.nullable(),
  connection: connectionTechnicalSchema.nullable(),
})

export const adminOnesStatusSchema = z.object({
  user_id: z.string(),
  ones: adminOnesTechnicalSchema.nullable(),
})

export const identityProviderSchema = z.object({
  code: externalIdentityProviderSchema,
  display_name: z.string(),
  available: z.boolean(),
  instance_code: z.string().optional(),
})

export type BindOnesInput = {
  expected_user_revision: number
  email: string
  password: string
}

export const onesBindingChallengeSchema = z.object({
  id: z.string(),
  provider: z.literal("ones"),
  connection_revision_id: z.string(),
  external_user_id: z.string(),
  display_name: z.string(),
  teams: z.array(teamSchema),
  team_ids: z.array(z.string()),
  expires_at: z.string(),
  status: z.string(),
  created_at: z.string(),
})

export const identityMutationSchema = z.object({
  id: z.string(),
  status: externalIdentityStatusSchema,
  revision: z.number().int().positive(),
})

export type AdminExternalIdentity = z.infer<typeof adminExternalIdentitySchema>
export type AdminDingTalkIdentity = z.infer<typeof adminDingTalkIdentitySchema>
export type AdminOnesIdentity = z.infer<typeof adminOnesIdentitySchema>
export type SelfDingTalkIdentity = z.infer<typeof selfDingTalkIdentitySchema>
export type SelfOnesIdentity = z.infer<typeof selfOnesIdentitySchema>
export type IdentityProvider = z.infer<typeof identityProviderSchema>
export type OnesBindingChallenge = z.infer<typeof onesBindingChallengeSchema>
