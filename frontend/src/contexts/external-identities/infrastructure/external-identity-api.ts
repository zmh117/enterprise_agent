import { z } from "zod"

import {
  adminExternalIdentityOverviewSchema,
  adminOnesStatusSchema,
  identityMutationSchema,
  identityProviderSchema,
  onesBindingChallengeSchema,
  selfExternalIdentityOverviewSchema,
  selfOnesStatusSchema,
} from "@/contexts/external-identities/domain/external-identity"
import { apiRequest } from "@/shared/api/api-client"

const identityResponseSchema = z.object({ identity: identityMutationSchema })

export async function listExternalIdentities(userId: string) {
  return adminExternalIdentityOverviewSchema.parse(
    await apiRequest(
      `/api/admin/users/${encodeURIComponent(userId)}/external-identities`
    )
  )
}

export async function listIdentityProviders() {
  return z
    .object({ providers: z.array(identityProviderSchema) })
    .parse(await apiRequest("/api/admin/external-identity-providers")).providers
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
  return selfOnesStatusSchema.parse(
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
  return selfOnesStatusSchema.parse(
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
  return adminOnesStatusSchema.parse(
    await apiRequest(
      `/api/admin/users/${encodeURIComponent(userId)}/external-credentials/ones`
    )
  )
}

export async function disableAdminOnesCredential(userId: string) {
  return adminOnesStatusSchema.parse(
    await apiRequest(
      `/api/admin/users/${encodeURIComponent(userId)}/external-credentials/ones/disable`,
      { method: "PUT" }
    )
  )
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
