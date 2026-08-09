import type { AuthenticatedUserEnvelope } from "@/contexts/auth/domain/authenticated-user"
import { apiRequest } from "@/shared/api/api-client"
import { z } from "zod"

export function getCurrentUser() {
  return apiRequest<AuthenticatedUserEnvelope>("/api/auth/me")
}

export function login(username: string, password: string) {
  return apiRequest<AuthenticatedUserEnvelope>("/api/auth/login", {
    method: "POST",
    body: { username, password },
  })
}

export function logout() {
  return apiRequest<{ status: "logged_out" }>("/api/auth/logout", {
    method: "POST",
  })
}

const sessionSchema = z.object({
  id: z.string(),
  status: z.string(),
  created_at: z.string(),
  last_seen_at: z.string(),
  idle_expires_at: z.string(),
  absolute_expires_at: z.string(),
  revoked_at: z.string().nullable().optional(),
  user_agent_summary: z.string().default(""),
  remote_address_summary: z.string().default(""),
})

export type UserSession = z.infer<typeof sessionSchema>

export async function listSessions() {
  return z.object({ sessions: z.array(sessionSchema) }).parse(
    await apiRequest("/api/auth/sessions")
  ).sessions
}

export function revokeSession(sessionId: string) {
  return apiRequest<{ status: "revoked" }>(
    `/api/auth/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" }
  )
}

export function changePassword(currentPassword: string, newPassword: string) {
  return apiRequest<{ status: "password_changed" }>("/api/auth/password", {
    method: "POST",
    body: {
      current_password: currentPassword,
      new_password: newPassword,
    },
  })
}
