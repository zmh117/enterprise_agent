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

export const userRoleSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  description: z.string(),
  status: z.string(),
  origin: z.string(),
  protected: z.union([z.boolean(), z.number()]).transform(Boolean),
  membership_id: z.string(),
  membership_status: z.string(),
  membership_revision: z.number(),
  expires_at: z.string().nullable().optional(),
  assigned_by: z.string().optional(),
  assignment_source: z.string().optional(),
})

export const userAuthorizationSummarySchema = z.object({
  roles: z.array(userRoleSchema),
  management_capabilities: z.array(z.string()),
  business_applications: z.array(
    z.object({
      id: z.string(),
      code: z.string(),
      name: z.string(),
      source_role_codes: z.array(z.string()),
      capability_codes: z.array(z.string()),
      scopes: z.array(z.record(z.string(), z.unknown())),
    }),
  ),
  access_status: z.string(),
})

export const userDetailSchema = userSchema.extend({
  roles: z.array(userRoleSchema).default([]),
  authorization_summary: userAuthorizationSummarySchema.default({
    roles: [],
    management_capabilities: [],
    business_applications: [],
    access_status: "未获得应用权限",
  }),
})

export const userPaginationSchema = z.object({
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
  total: z.number().int().nonnegative(),
  total_pages: z.number().int().nonnegative(),
})

export type User = z.infer<typeof userSchema>
export type UserDetail = z.infer<typeof userDetailSchema>
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
