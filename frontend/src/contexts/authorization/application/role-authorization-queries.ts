import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type {
  CreateRoleInput,
  ExplanationInput,
} from "@/contexts/authorization/domain/role-authorization"
import {
  createRole,
  explainAuthorization,
  getAdminCapabilityCatalog,
  getAssignableCatalog,
  getRole,
  getRoleAudit,
  listRoles,
  updateRoleAdminCapabilities,
  updateRoleBusinessAccess,
  updateRoleMembers,
  updateRoleMetadata,
  updateUserRoles,
} from "@/contexts/authorization/infrastructure/role-authorization-api"

export const roleKeys = {
  all: ["role-authorization"] as const,
  list: (params: object) => [...roleKeys.all, "list", params] as const,
  detail: (roleId: string) => [...roleKeys.all, "detail", roleId] as const,
  audit: (roleId: string) => [...roleKeys.all, "audit", roleId] as const,
  capabilities: () => [...roleKeys.all, "capabilities"] as const,
  catalog: () => [...roleKeys.all, "catalog"] as const,
}

export function useRoles(params: {
  search: string
  status: string
  origin: string
}) {
  return useQuery({
    queryKey: roleKeys.list(params),
    queryFn: () => listRoles(params),
    retry: false,
  })
}

export function useRole(roleId: string) {
  return useQuery({
    queryKey: roleKeys.detail(roleId),
    queryFn: () => getRole(roleId),
    enabled: Boolean(roleId),
    retry: false,
  })
}

export function useRoleAudit(roleId: string) {
  return useQuery({
    queryKey: roleKeys.audit(roleId),
    queryFn: () => getRoleAudit(roleId),
    enabled: Boolean(roleId),
    retry: false,
  })
}

export function useAdminCapabilityCatalog() {
  return useQuery({
    queryKey: roleKeys.capabilities(),
    queryFn: getAdminCapabilityCatalog,
    retry: false,
  })
}

export function useAssignableCatalog() {
  return useQuery({
    queryKey: roleKeys.catalog(),
    queryFn: getAssignableCatalog,
    retry: false,
  })
}

function useRoleMutation(
  roleId: string,
  mutationFn: (input: Record<string, unknown>) => Promise<unknown>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: roleKeys.detail(roleId) }),
        queryClient.invalidateQueries({ queryKey: roleKeys.all }),
        queryClient.invalidateQueries({
          queryKey: ["auth", "admin-capabilities"],
        }),
      ])
    },
  })
}

export function useCreateRole() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateRoleInput) => createRole(input),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: roleKeys.all }),
  })
}

export function useUpdateRoleMetadata(roleId: string) {
  return useRoleMutation(roleId, (input) => updateRoleMetadata(roleId, input))
}

export function useUpdateRoleAdmin(roleId: string) {
  return useRoleMutation(roleId, (input) =>
    updateRoleAdminCapabilities(roleId, input),
  )
}

export function useUpdateRoleBusiness(roleId: string) {
  return useRoleMutation(roleId, (input) =>
    updateRoleBusinessAccess(roleId, input),
  )
}

export function useUpdateRoleMembers(roleId: string) {
  return useRoleMutation(roleId, (input) => updateRoleMembers(roleId, input))
}

export function useUpdateUserRoles(userId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: Record<string, unknown>) =>
      updateUserRoles(userId, input),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: roleKeys.all }),
        queryClient.invalidateQueries({
          queryKey: ["users", "detail", userId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["auth", "admin-capabilities"],
        }),
      ])
    },
  })
}

export function useExplainAuthorization() {
  return useMutation({
    mutationFn: (input: ExplanationInput) => explainAuthorization(input),
  })
}
