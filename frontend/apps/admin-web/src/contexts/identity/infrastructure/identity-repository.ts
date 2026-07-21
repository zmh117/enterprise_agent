import { jsonBody, request } from "@enterprise-agent/api-client";

import type { DingTalkTenant, ExternalIdentity, Principal, RoleAssignment, User, UserDetail } from "../domain/models";

export const identityRepository = {
  currentPrincipal: () => request<{ user: Principal }>("/api/auth/me"),
  adminCapabilities: () => request<{ capabilities: string[] }>("/api/admin/capabilities"),
  login: (username: string, password: string) => request<{ user: Principal }>("/api/auth/login", { method: "POST", ...jsonBody({ username, password }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  listUsers: () => request<{ users: User[] }>("/api/admin/users"),
  getUser: (userId: string) => request<UserDetail>(`/api/admin/users/${userId}`),
  listTenants: () => request<{ tenants: DingTalkTenant[] }>("/api/admin/dingtalk-tenants"),
  createUser: (input: { username: string; display_name: string; email: string; password: string | null }) => request<{ user: User }>("/api/admin/users", { method: "POST", ...jsonBody(input) }),
  updateUserStatus: (user: User, status: User["status"]) => request(`/api/admin/users/${user.id}`, { method: "PUT", ...jsonBody({ expected_revision: user.revision, display_name: user.display_name, email: user.email, status }) }),
  setRole: (userId: string, role: RoleAssignment, enabled: boolean, expectedRevision: number) => request(`/api/admin/users/${userId}/roles`, { method: "POST", ...jsonBody({ role_id: role.id, enabled, expected_revision: expectedRevision }) }),
  bindDingTalk: (user: User, input: { tenant_code: string; connector_id: string; external_subject_id: string; display_name: string }) => request(`/api/admin/users/${user.id}/dingtalk-identities`, { method: "POST", ...jsonBody({ expected_user_revision: user.revision, ...input }) }),
  toggleIdentity: (identity: ExternalIdentity) => request(`/api/admin/identities/${identity.id}/status`, { method: "PUT", ...jsonBody({ expected_revision: identity.revision, status: identity.status === "enabled" ? "disabled" : "enabled" }) }),
  revokeSession: (userId: string, sessionId: string) => request(`/api/admin/users/${userId}/sessions/${sessionId}`, { method: "DELETE" }),
};
