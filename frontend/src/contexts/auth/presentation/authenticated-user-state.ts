import { createContext, useContext } from "react"

import type { AuthenticatedUser } from "@/contexts/auth/domain/authenticated-user"

export type AuthenticatedSession = {
  user: AuthenticatedUser
  logout: () => Promise<void>
}

export const AuthenticatedUserContext =
  createContext<AuthenticatedSession | null>(null)

export function useAuthenticatedUser() {
  const session = useContext(AuthenticatedUserContext)
  if (!session) {
    throw new Error("AuthenticatedUserProvider is required")
  }
  return session.user
}

export function useLogout() {
  const session = useContext(AuthenticatedUserContext)
  if (!session) {
    throw new Error("AuthenticatedUserProvider is required")
  }
  return session.logout
}
