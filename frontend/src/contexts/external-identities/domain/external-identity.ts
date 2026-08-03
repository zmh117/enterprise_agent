import { z } from "zod"

export const externalIdentityProviderSchema = z.enum(["dingtalk", "ones"])
export const externalIdentityStatusSchema = z.enum([
  "enabled",
  "disabled",
  "unbound",
])

export const externalIdentitySchema = z.object({
  id: z.string(),
  user_id: z.string(),
  provider: externalIdentityProviderSchema,
  tenant_code: z.string(),
  external_subject_id: z.string(),
  connector_id: z.string(),
  union_id: z.string(),
  open_id: z.string(),
  display_name: z.string(),
  status: externalIdentityStatusSchema,
  verified_at: z.string().nullable().optional(),
  last_seen_at: z.string().nullable().optional(),
  metadata: z.object({
    verification_method: z.string().optional(),
    team_uuids: z.array(z.string()).optional(),
    default_team_id: z.string().optional(),
  }),
  revision: z.number().int().positive(),
  created_at: z.string(),
  updated_at: z.string(),
})

export const identityProviderSchema = z.object({
  code: externalIdentityProviderSchema,
  display_name: z.string(),
  available: z.boolean(),
  instance_code: z.string().optional(),
})

export const dingtalkTenantSchema = z.object({
  connector_id: z.string(),
  name: z.string(),
  tenant_code: z.string(),
})

export type ExternalIdentity = z.infer<typeof externalIdentitySchema>
export type IdentityProvider = z.infer<typeof identityProviderSchema>
export type DingTalkTenant = z.infer<typeof dingtalkTenantSchema>

export type BindDingTalkInput = {
  expected_user_revision: number
  tenant_code: string
  external_subject_id: string
  connector_id: string
  display_name: string
}

export type BindOnesInput = {
  expected_user_revision: number
  email: string
  password: string
}

export const externalCredentialSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  external_identity_id: z.string(),
  provider: z.literal("ones"),
  connection_revision_id: z.string(),
  status: z.enum(["ACTIVE", "INVALID", "DISABLED", "UNBOUND"]),
  revision: z.number(),
  last_error_code: z.string(),
  verified_at: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
})

export const onesBindingStatusSchema = z.object({
  user: z
    .object({
      id: z.string(),
      display_name: z.string(),
    })
    .optional(),
  user_id: z.string().optional(),
  identity: externalIdentitySchema.nullable().optional(),
  credential: externalCredentialSchema.nullable(),
})

export const selfExternalIdentityOverviewSchema = z.object({
  user: z.object({
    id: z.string(),
    display_name: z.string(),
  }),
  identities: z.array(externalIdentitySchema),
  credentials: z.object({
    ones: externalCredentialSchema.nullable(),
  }),
})

export const onesBindingChallengeSchema = z.object({
  id: z.string(),
  provider: z.literal("ones"),
  connection_revision_id: z.string(),
  external_user_id: z.string(),
  display_name: z.string(),
  teams: z.array(z.object({ id: z.string(), name: z.string() })),
  team_ids: z.array(z.string()),
  expires_at: z.string(),
  status: z.string(),
  created_at: z.string(),
})

export type ExternalCredential = z.infer<typeof externalCredentialSchema>
export type OnesBindingStatus = z.infer<typeof onesBindingStatusSchema>
export type SelfExternalIdentityOverview = z.infer<
  typeof selfExternalIdentityOverviewSchema
>
export type OnesBindingChallenge = z.infer<typeof onesBindingChallengeSchema>
