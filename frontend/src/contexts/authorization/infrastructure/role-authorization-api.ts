import { z } from "zod"

import {
  adminCapabilitySchema,
  catalogApplicationSchema,
  environmentSchema,
  roleDetailSchema,
  roleAuditSchema,
  roleSchema,
  type CreateRoleInput,
  type ExplanationInput,
} from "@/contexts/authorization/domain/role-authorization"
import { apiRequest } from "@/shared/api/api-client"

const roleListSchema = z.object({
  items: z.array(roleSchema),
  page: z.object({
    limit: z.number(),
    offset: z.number(),
    total: z.number(),
  }),
})

const capabilityCatalogSchema = z.object({
  items: z.array(adminCapabilitySchema),
})

const assignableCatalogSchema = z.object({
  applications: z.array(catalogApplicationSchema),
  topology: z.array(environmentSchema),
  scope_mode: z.literal("explicit_current_set"),
  scope_notice: z.string(),
})

export async function listRoles(params: {
  search: string
  status: string
  origin: string
}) {
  const query = new URLSearchParams({
    search: params.search,
    status: params.status,
    origin: params.origin,
    limit: "100",
    offset: "0",
  })
  return roleListSchema.parse(
    await apiRequest(`/api/admin/authorization/roles?${query.toString()}`),
  )
}

export async function getRole(roleId: string) {
  return roleDetailSchema.parse(
    await apiRequest(
      `/api/admin/authorization/roles/${encodeURIComponent(roleId)}`,
    ),
  )
}

export async function getRoleAudit(roleId: string) {
  return roleAuditSchema.parse(
    await apiRequest(
      `/api/admin/authorization/roles/${encodeURIComponent(roleId)}/audit`,
    ),
  )
}

export async function createRole(input: CreateRoleInput) {
  return roleDetailSchema.parse(
    await apiRequest("/api/admin/authorization/roles", {
      method: "POST",
      body: input,
    }),
  )
}

export async function getAdminCapabilityCatalog() {
  return capabilityCatalogSchema.parse(
    await apiRequest("/api/admin/authorization/capabilities"),
  )
}

export async function getAssignableCatalog() {
  return assignableCatalogSchema.parse(
    await apiRequest("/api/admin/authorization/assignable-catalog"),
  )
}

export async function updateRoleMetadata(
  roleId: string,
  input: Record<string, unknown>,
) {
  const response = z
    .object({ role: roleSchema })
    .parse(
      await apiRequest(
        `/api/admin/authorization/roles/${encodeURIComponent(roleId)}/metadata`,
        { method: "PUT", body: input },
      ),
    )
  return response.role
}

export async function updateRoleAdminCapabilities(
  roleId: string,
  input: Record<string, unknown>,
) {
  return apiRequest(
    `/api/admin/authorization/roles/${encodeURIComponent(roleId)}/admin-capabilities`,
    { method: "PUT", body: input },
  )
}

export async function updateRoleBusinessAccess(
  roleId: string,
  input: Record<string, unknown>,
) {
  return apiRequest(
    `/api/admin/authorization/roles/${encodeURIComponent(roleId)}/business-access`,
    { method: "PUT", body: input },
  )
}

export async function updateRoleMembers(
  roleId: string,
  input: Record<string, unknown>,
) {
  return apiRequest(
    `/api/admin/authorization/roles/${encodeURIComponent(roleId)}/members:batch`,
    { method: "POST", body: input },
  )
}

export async function updateUserRoles(
  userId: string,
  input: Record<string, unknown>,
) {
  return apiRequest(
    `/api/admin/authorization/users/${encodeURIComponent(userId)}/roles:batch`,
    { method: "POST", body: input },
  )
}

export async function explainAuthorization(input: ExplanationInput) {
  return z
    .object({
      decision: z.object({
        allowed: z.boolean(),
        stage: z.string(),
        reason: z.string(),
        source_role_codes: z.array(z.string()),
        application: z.object({ id: z.string(), code: z.string() }),
        tool_identifier: z.string(),
        scope: z.record(z.string(), z.string()),
      }),
      notice: z.string(),
    })
    .parse(
      await apiRequest("/api/admin/authorization/explanations", {
        method: "POST",
        body: input,
      }),
    )
}
