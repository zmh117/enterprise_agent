import { z } from "zod"

export const externalIdentityProviderSchema = z.literal("dingtalk")
export const externalIdentityStatusSchema = z.enum([
  "enabled",
  "disabled",
  "unbound",
])

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

export const adminExternalIdentitySchema = adminDingTalkIdentitySchema

export const adminExternalIdentityOverviewSchema = z.object({
  user_id: z.string(),
  current: z.array(adminExternalIdentitySchema),
  history: z.array(adminExternalIdentitySchema),
})

export const selfExternalIdentityOverviewSchema = z.object({
  user: z.object({ id: z.string(), display_name: z.string() }),
  dingtalk: z.array(selfDingTalkIdentitySchema),
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
export type SelfDingTalkIdentity = z.infer<typeof selfDingTalkIdentitySchema>
export type IdentityProvider = z.infer<typeof identityProviderSchema>
