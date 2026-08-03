import { type ReactNode } from "react"

import type { AuthenticatedUser } from "@/contexts/auth/domain/authenticated-user"
import { AuthenticatedUserContext } from "@/contexts/auth/presentation/authenticated-user-state"

export function AuthenticatedUserProvider({
  user,
  logout = async () => undefined,
  children,
}: {
  user: AuthenticatedUser
  logout?: () => Promise<void>
  children: ReactNode
}) {
  return (
    <AuthenticatedUserContext.Provider value={{ user, logout }}>
      {children}
    </AuthenticatedUserContext.Provider>
  )
}
