import type { AuthenticatedUserEnvelope } from "@/contexts/auth/domain/authenticated-user"
import { apiRequest } from "@/shared/api/api-client"

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
