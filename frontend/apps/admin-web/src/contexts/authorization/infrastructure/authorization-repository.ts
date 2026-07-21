import { jsonBody, request } from "@enterprise-agent/api-client";

import type { AuditEvent, Role, RoleDetail } from "../domain/models";

export const authorizationRepository = {
  listRoles: () => request<{ roles: Role[] }>("/api/admin/roles"),
  getRole: (roleId: string) => request<RoleDetail>(`/api/admin/roles/${roleId}`),
  createRole: (input: { code: string; name: string; description: string }) => request<{ role: Role }>("/api/admin/roles", { method: "POST", ...jsonBody(input) }),
  toggleRoleStatus: (role: Role) => request(`/api/admin/roles/${role.id}`, { method: "PUT", ...jsonBody({ expected_revision: role.revision, name: role.name, description: role.description, status: role.status === "enabled" ? "disabled" : "enabled" }) }),
  createPermission: (role: Role, input: { resource_type: string; resource_code: string; action: string; effect: string; priority: number }) => request("/api/admin/permissions", { method: "POST", ...jsonBody({ id: null, subject_type: "role", subject_code: role.code, ...input, status: "enabled", expected_revision: 0 }) }),
  listAuditEvents: () => request<{ events: AuditEvent[] }>("/api/admin/audit-events?limit=300"),
};

