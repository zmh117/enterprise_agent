import { z } from "zod"

import {
  adminExternalIdentityOverviewSchema,
  identityMutationSchema,
  identityProviderSchema,
  selfExternalIdentityOverviewSchema,
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

export async function getSelfExternalIdentities() {
  return selfExternalIdentityOverviewSchema.parse(
    await apiRequest("/api/me/external-identities")
  )
}
