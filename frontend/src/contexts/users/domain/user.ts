import { z } from "zod"

export const userStatusSchema = z.enum(["enabled", "disabled"])
export const accountTypeSchema = z.enum(["human", "service"])

export const userSchema = z.object({
  id: z.string(),
  username: z.string(),
  display_name: z.string(),
  email: z.string(),
  status: userStatusSchema,
  account_type: accountTypeSchema,
  revision: z.number().int().positive(),
  created_at: z.string(),
  updated_at: z.string(),
})

export const userPaginationSchema = z.object({
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
  total: z.number().int().nonnegative(),
  total_pages: z.number().int().nonnegative(),
})

export type User = z.infer<typeof userSchema>
export type UserStatus = z.infer<typeof userStatusSchema>
export type UserPagination = z.infer<typeof userPaginationSchema>

export type UserListParams = {
  search: string
  page: number
  pageSize: number
  includeDisabled: boolean
}

export type CreateUserInput = {
  username: string
  display_name: string
  email: string
  password?: string
}

export type UpdateUserInput = {
  expected_revision: number
  display_name: string
  email: string
  status: UserStatus
}
