export type AuthenticatedUser = {
  id: string
  username: string
  display_name: string
  roles: string[]
  auth_source: string
  capabilities: Record<string, boolean>
}

export type AuthenticatedUserEnvelope = {
  user: AuthenticatedUser
}
