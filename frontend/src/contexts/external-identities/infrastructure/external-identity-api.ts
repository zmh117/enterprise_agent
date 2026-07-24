import { z } from "zod"

import {
  dingtalkTenantSchema,
  externalIdentitySchema,
  identityProviderSchema,
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
    .parse(
      await apiRequest(`/api/admin/users/${encodeURIComponent(userId)}`),
    ).identities
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
  input: BindDingTalkInput,
) {
  return identityResponseSchema.parse(
    await apiRequest(
      `/api/admin/users/${encodeURIComponent(userId)}/dingtalk-identities`,
      { method: "POST", body: input },
    ),
  ).identity
}

export async function bindOnesIdentity(userId: string, input: BindOnesInput) {
  return identityResponseSchema.parse(
    await apiRequest(
      `/api/admin/users/${encodeURIComponent(userId)}/ones-identities`,
      { method: "POST", body: input },
    ),
  ).identity
}

export async function updateIdentityStatus(
  identityId: string,
  input: { expected_revision: number; status: "enabled" | "disabled" },
) {
  return identityResponseSchema.parse(
    await apiRequest(
      `/api/admin/identities/${encodeURIComponent(identityId)}/status`,
      { method: "PUT", body: input },
    ),
  ).identity
}

export async function unbindIdentity(
  identityId: string,
  expectedRevision: number,
) {
  const query = new URLSearchParams({
    expected_revision: String(expectedRevision),
  })
  return identityResponseSchema.parse(
    await apiRequest(
      `/api/admin/identities/${encodeURIComponent(identityId)}?${query.toString()}`,
      { method: "DELETE" },
    ),
  ).identity
}
