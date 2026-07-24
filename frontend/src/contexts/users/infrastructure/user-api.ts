import { z } from "zod"

import {
  userPaginationSchema,
  userSchema,
  type CreateUserInput,
  type UpdateUserInput,
  type UserListParams,
} from "@/contexts/users/domain/user"
import { apiRequest } from "@/shared/api/api-client"

const listResponseSchema = z.object({
  users: z.array(userSchema),
  pagination: userPaginationSchema,
})

const userResponseSchema = z.object({
  user: userSchema,
})

export async function listUsers(params: UserListParams) {
  const query = new URLSearchParams({
    search: params.search,
    page: String(params.page),
    page_size: String(params.pageSize),
    include_disabled: String(params.includeDisabled),
  })
  return listResponseSchema.parse(
    await apiRequest(`/api/admin/users?${query.toString()}`),
  )
}

export async function getUser(userId: string) {
  return userResponseSchema.parse(
    await apiRequest(`/api/admin/users/${encodeURIComponent(userId)}`),
  ).user
}

export async function createUser(input: CreateUserInput) {
  return userResponseSchema.parse(
    await apiRequest("/api/admin/users", {
      method: "POST",
      body: {
        ...input,
        password: input.password || undefined,
      },
    }),
  ).user
}

export async function updateUser(userId: string, input: UpdateUserInput) {
  return userResponseSchema.parse(
    await apiRequest(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: "PUT",
      body: input,
    }),
  ).user
}
