import { z } from "zod"

import {
  userPaginationSchema,
  userDetailSchema,
  userRoleSchema,
  userAuthorizationSummarySchema,
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

const userDetailResponseSchema = z.object({
  user: userSchema,
  roles: z.array(userRoleSchema).default([]),
  authorization_summary: userAuthorizationSummarySchema.default({
    roles: [],
    management_capabilities: [],
    business_applications: [],
    access_status: "未获得应用权限",
  }),
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
  const response = userDetailResponseSchema.parse(
    await apiRequest(`/api/admin/users/${encodeURIComponent(userId)}`),
  )
  return userDetailSchema.parse({
    ...response.user,
    roles: response.roles,
    authorization_summary: response.authorization_summary,
  })
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
