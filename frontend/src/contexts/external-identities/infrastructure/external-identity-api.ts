import { z } from "zod"

import {
  dingtalkTenantSchema,
  externalIdentitySchema,
  identityProviderSchema,
  onesBindingChallengeSchema,
  onesBindingStatusSchema,
  selfExternalIdentityOverviewSchema,
  type BindDingTalkInput,
  type BindOnesInput,
} from "@/contexts/external-identities/domain/external-identity"
import { apiRequest } from "@/shared/api/api-client"

const identityResponseSchema = z.object({
  identity: externalIdentitySchema,
})

export async function listExternalIdentities(userId: string) {
  return z
    .object({ identities: z.array(externalIdentitySchema) })
    .parse(await apiRequest(`/api/admin/users/${encodeURIComponent(userId)}`))
    .identities
}

export async function listIdentityProviders() {
  return z
    .object({ providers: z.array(identityProviderSchema) })
    .parse(await apiRequest("/api/admin/external-identity-providers")).providers
}

export async function listDingTalkTenants() {
  return z
    .object({ tenants: z.array(dingtalkTenantSchema) })
    .parse(await apiRequest("/api/admin/dingtalk-tenants")).tenants
}

export async function bindDingTalkIdentity(
  userId: string,
  input: BindDingTalkInput
) {
  return identityResponseSchema.parse(
    await apiRequest(
      `/api/admin/users/${encodeURIComponent(userId)}/dingtalk-identities`,
      { method: "POST", body: input }
    )
  ).identity
}

export async function bindOnesIdentity(userId: string, input: BindOnesInput) {
  return identityResponseSchema.parse(
    await apiRequest(
      `/api/admin/users/${encodeURIComponent(userId)}/ones-identities`,
      { method: "POST", body: input }
    )
  ).identity
}

export async function updateIdentityStatus(
  identityId: string,
  input: { expected_revision: number; status: "enabled" | "disabled" }
) {
  return identityResponseSchema.parse(
    await apiRequest(
      `/api/admin/identities/${encodeURIComponent(identityId)}/status`,
      { method: "PUT", body: input }
    )
  ).identity
}

export async function unbindIdentity(
  identityId: string,
  expectedRevision: number
) {
  const query = new URLSearchParams({
    expected_revision: String(expectedRevision),
  })
  return identityResponseSchema.parse(
    await apiRequest(
      `/api/admin/identities/${encodeURIComponent(identityId)}?${query.toString()}`,
      { method: "DELETE" }
    )
  ).identity
}

export async function getSelfOnesBinding() {
  return onesBindingStatusSchema.parse(
    await apiRequest("/api/me/external-identities/ones")
  )
}

export async function getSelfExternalIdentities() {
  return selfExternalIdentityOverviewSchema.parse(
    await apiRequest("/api/me/external-identities")
  )
}

export async function beginSelfOnesBinding(input: {
  email: string
  password: string
  connection_revision_id?: string
}) {
  return z.object({ challenge: onesBindingChallengeSchema }).parse(
    await apiRequest("/api/me/external-identities/ones/challenges", {
      method: "POST",
      body: input,
    })
  ).challenge
}

export async function confirmSelfOnesBinding(input: {
  challenge_id: string
  connection_revision_id: string
  default_team_id: string
  replace_existing: boolean
}) {
  return z
    .object({
      identity: externalIdentitySchema,
      credential: onesBindingStatusSchema.shape.credential.unwrap(),
    })
    .parse(
      await apiRequest("/api/me/external-identities/ones/confirm", {
        method: "POST",
        body: input,
      })
    )
}

export async function unbindSelfOnesBinding() {
  return z.object({ status: z.literal("unbound") }).parse(
    await apiRequest("/api/me/external-identities/ones", {
      method: "DELETE",
    })
  )
}

export async function getAdminOnesCredential(userId: string) {
  return onesBindingStatusSchema.parse(
    await apiRequest(
      `/api/admin/users/${encodeURIComponent(userId)}/external-credentials/ones`
    )
  )
}

export async function disableAdminOnesCredential(userId: string) {
  return z
    .object({
      credential: onesBindingStatusSchema.shape.credential.unwrap(),
    })
    .parse(
      await apiRequest(
        `/api/admin/users/${encodeURIComponent(userId)}/external-credentials/ones/disable`,
        { method: "PUT" }
      )
    ).credential
}

export async function unbindAdminOnesCredential(userId: string) {
  return z
    .object({ status: z.literal("unbound") })
    .parse(
      await apiRequest(
        `/api/admin/users/${encodeURIComponent(userId)}/external-credentials/ones`,
        { method: "DELETE" }
      )
    )
}
