import { apiRequest, createIdempotencyKey } from "@/shared/api/api-client"

export type AdminUser = {
  id: string
  username: string
  display_name: string
  email: string
  status: "enabled" | "disabled"
  account_type: "human" | "service"
  revision: number
  created_at: string
  updated_at: string
}

export type UserRole = {
  id: string
  code: string
  name: string
  status: string
  protected: boolean | number
  membership_id: string
  membership_status: string
  membership_revision: number
}

export type ExternalIdentitySummary = {
  id: string
  provider: string
  tenant_code: string
  display_name: string
  status: string
  credential_status: string
  verified_at?: string | null
  last_seen_at?: string | null
  revision: number
}

export type UserSessionSummary = {
  id: string
  status: string
  created_at: string
  last_seen_at: string
  idle_expires_at: string
  absolute_expires_at: string
  user_agent_summary: string
  remote_address_summary: string
}

export type UserDetail = {
  user: AdminUser
  roles: UserRole[]
  sessions: UserSessionSummary[]
  external_identities: ExternalIdentitySummary[]
}

export type RoleSummary = {
  id: string
  code: string
  name: string
  description: string
  status: "enabled" | "disabled"
  origin: "system" | "custom"
  protected: boolean
  purpose_tags: string[]
  metadata_revision: number
  admin_revision: number
  business_revision: number
  membership_revision: number
  member_count: number
  admin_capability_count: number
  application_count: number
}

export type AdminCapability = {
  code: string
  module: string
  resource_type: string
  resource_code: string
  action: string
  display_name_zh: string
  risk_level: "low" | "medium" | "high"
  dependencies: string[]
  assignable: boolean
}

export type AssignableApplication = {
  id: string
  code: string
  name: string
  description: string
  project_code: string
  status: string
}

export type RoleDetail = {
  role: RoleSummary
  admin: {
    revision: number
    bindings: Array<{ capability_code: string }>
    implicit_all: boolean
  }
  business: {
    revision: number
    applications: Array<{
      id: string
      application_id: string
      application_code: string
      application_name: string
      status: string
    }>
  }
  membership: {
    revision: number
    members: Array<
      AdminUser & {
        membership_id: string
        membership_status: string
        membership_revision: number
      }
    >
  }
}

export async function listUsers(search = "") {
  const query = new URLSearchParams({
    search,
    page: "1",
    page_size: "100",
    include_disabled: "true",
  })
  return apiRequest<{
    users: AdminUser[]
    pagination: { page: number; page_size: number; total: number; total_pages: number }
  }>(`/api/admin/users?${query.toString()}`)
}

export async function getUser(userId: string) {
  return apiRequest<UserDetail>(`/api/admin/users/${encodeURIComponent(userId)}`)
}

export async function createUser(input: {
  username: string
  display_name: string
  email: string
  password?: string
}) {
  return apiRequest<{ user: AdminUser }>("/api/admin/users", {
    method: "POST",
    headers: { "Idempotency-Key": createIdempotencyKey("user-create") },
    body: input,
  })
}

export async function updateUser(
  userId: string,
  input: {
    expected_revision: number
    display_name: string
    email: string
    status: "enabled" | "disabled"
  }
) {
  return apiRequest<{ user: AdminUser }>(
    `/api/admin/users/${encodeURIComponent(userId)}`,
    {
      method: "PUT",
      headers: { "Idempotency-Key": createIdempotencyKey("user-update") },
      body: input,
    }
  )
}

export async function revokeUserSession(userId: string, sessionId: string) {
  return apiRequest<{ status: string }>(
    `/api/admin/users/${encodeURIComponent(userId)}/sessions/${encodeURIComponent(sessionId)}/revoke`,
    {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("user-session-revoke") },
      body: {},
    }
  )
}

export async function listRoles(search = "") {
  const query = new URLSearchParams({ search, limit: "100", offset: "0" })
  return apiRequest<{
    items: RoleSummary[]
    page: { limit: number; offset: number; total: number }
  }>(`/api/admin/authorization/roles?${query.toString()}`)
}

export async function getRole(roleId: string) {
  return apiRequest<RoleDetail>(
    `/api/admin/authorization/roles/${encodeURIComponent(roleId)}`
  )
}

export async function createRole(input: {
  code: string
  name: string
  description: string
  purpose_tags: string[]
}) {
  return apiRequest<RoleDetail>("/api/admin/authorization/roles", {
    method: "POST",
    headers: { "Idempotency-Key": createIdempotencyKey("role-create") },
    body: input,
  })
}

export async function listAdminCapabilities() {
  const result = await apiRequest<{ items: AdminCapability[] }>(
    "/api/admin/authorization/capabilities"
  )
  return result.items
}

export async function listAssignableApplications() {
  const result = await apiRequest<{ items: AssignableApplication[] }>(
    "/api/admin/authorization/assignable-applications"
  )
  return result.items
}

export async function updateRoleMetadata(
  roleId: string,
  input: {
    expected_revision: number
    name: string
    description: string
    purpose_tags: string[]
    status: "enabled" | "disabled"
  }
) {
  return apiRequest<{ role: RoleSummary }>(
    `/api/admin/authorization/roles/${encodeURIComponent(roleId)}/metadata`,
    {
      method: "PUT",
      headers: { "Idempotency-Key": createIdempotencyKey("role-metadata") },
      body: input,
    }
  )
}

export async function updateRoleCapabilities(
  roleId: string,
  expectedRevision: number,
  capabilityCodes: string[]
) {
  return apiRequest<Record<string, unknown>>(
    `/api/admin/authorization/roles/${encodeURIComponent(roleId)}/admin-capabilities`,
    {
      method: "PUT",
      headers: { "Idempotency-Key": createIdempotencyKey("role-capabilities") },
      body: {
        expected_revision: expectedRevision,
        capability_codes: capabilityCodes,
      },
    }
  )
}

export async function updateRoleApplications(
  roleId: string,
  expectedRevision: number,
  applicationIds: string[]
) {
  return apiRequest<Record<string, unknown>>(
    `/api/admin/authorization/roles/${encodeURIComponent(roleId)}/business-access`,
    {
      method: "PUT",
      headers: { "Idempotency-Key": createIdempotencyKey("role-applications") },
      body: {
        expected_revision: expectedRevision,
        application_ids: applicationIds,
      },
    }
  )
}

export async function updateRoleMember(
  roleId: string,
  roleRevision: number,
  change: { user_id: string; enabled: boolean; expected_revision: number }
) {
  return apiRequest<Record<string, unknown>>(
    `/api/admin/authorization/roles/${encodeURIComponent(roleId)}/members:batch`,
    {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("role-members") },
      body: { expected_revision: roleRevision, changes: [change] },
    }
  )
}

