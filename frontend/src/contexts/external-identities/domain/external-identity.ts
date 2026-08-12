import { z } from "zod"

export const externalIdentityProviderSchema = z.enum(["dingtalk", "ones"])
export const externalIdentityStatusSchema = z.enum([
  "enabled",
  "disabled",
  "unbound",
])

const dingtalkEnterpriseSchema = z.object({
  name: z.string(),
  corp_id: z.string(),
})

export const onesTeamSchema = z.object({ id: z.string(), name: z.string() })

export const selfDingTalkIdentitySchema = z.object({
  provider: z.literal("dingtalk"),
  nickname: z.string(),
  status: z.enum(["enabled", "disabled"]),
  enterprise: dingtalkEnterpriseSchema.nullable(),
  last_used_at: z.string().nullable().optional(),
  staff_id: z.string(),
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

export const selfOnesIdentitySchema = z.object({
  provider: z.literal("ones"),
  user_name: z.string(),
  status: z.enum(["enabled", "disabled"]),
  default_team: onesTeamSchema.nullable(),
  verified_at: z.string().nullable().optional(),
  user_id: z.string(),
  teams: z.array(onesTeamSchema),
  credential: z
    .object({
      configured: z.boolean(),
      status: z.enum(["ACTIVE", "REAUTH_REQUIRED", "DISABLED", "UNBOUND"]),
      revision: z.number().int().positive(),
      verified_at: z.string(),
      token_refreshed_at: z.string().nullable(),
      last_used_at: z.string().nullable(),
      reauth_required_at: z.string().nullable(),
      disabled_at: z.string().nullable(),
      unbound_at: z.string().nullable(),
    })
    .nullable(),
})

export const adminOnesIdentitySchema = selfOnesIdentitySchema.extend({
  status: externalIdentityStatusSchema,
  identity_id: z.string(),
  revision: z.number().int().positive(),
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

export const onesIdentityChallengeSchema = z.object({
  id: z.string(),
  provider: z.literal("ones"),
  external_user_id: z.string(),
  display_name: z.string(),
  teams: z.array(onesTeamSchema),
  team_ids: z.array(z.string()),
  verified_at: z.string(),
  expires_at: z.string(),
  status: z.enum(["PENDING", "CONSUMED", "EXPIRED"]),
  created_at: z.string(),
})

export const identityProviderSchema = z.object({
  code: externalIdentityProviderSchema,
  display_name: z.string(),
  available: z.boolean(),
  instance_code: z.string().optional(),
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
export type OnesIdentityChallenge = z.infer<typeof onesIdentityChallengeSchema>
