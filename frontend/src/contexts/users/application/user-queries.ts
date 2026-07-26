import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type {
  CreateUserInput,
  UpdateUserInput,
  UserListParams,
} from "@/contexts/users/domain/user"
import {
  createUser,
  getUser,
  listUsers,
  updateUser,
} from "@/contexts/users/infrastructure/user-api"

export const userKeys = {
  all: ["users"] as const,
  listRoot: () => [...userKeys.all, "list"] as const,
  list: (params: UserListParams) => [...userKeys.listRoot(), params] as const,
  detail: (userId: string) => [...userKeys.all, "detail", userId] as const,
}

export function useUsers(params: UserListParams) {
  return useQuery({
    queryKey: userKeys.list(params),
    queryFn: () => listUsers(params),
    retry: false,
  })
}

export function useUser(userId: string) {
  return useQuery({
    queryKey: userKeys.detail(userId),
    queryFn: () => getUser(userId),
    enabled: Boolean(userId),
    retry: false,
  })
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateUserInput) => createUser(input),
    onSuccess: (user) => {
      queryClient.setQueryData(userKeys.detail(user.id), {
        ...user,
        roles: [],
        authorization_summary: {
          roles: [],
          management_capabilities: [],
          business_applications: [],
          access_status: "未获得应用权限",
        },
      })
      void queryClient.invalidateQueries({ queryKey: userKeys.detail(user.id) })
      void queryClient.invalidateQueries({ queryKey: userKeys.listRoot() })
    },
  })
}

export function useUpdateUser(userId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: UpdateUserInput) => updateUser(userId, input),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: userKeys.detail(user.id) })
      void queryClient.invalidateQueries({ queryKey: userKeys.listRoot() })
    },
  })
}
