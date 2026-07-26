import { z } from "zod"

export const roleSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  description: z.string(),
  status: z.enum(["enabled", "disabled"]),
  origin: z.enum(["system", "custom"]),
  protected: z.boolean(),
  purpose_tags: z.array(z.string()),
  metadata_revision: z.number(),
  admin_revision: z.number(),
  business_revision: z.number(),
  membership_revision: z.number(),
  member_count: z.number().optional().default(0),
  admin_capability_count: z.number().optional().default(0),
  application_count: z.number().optional().default(0),
})

export const adminCapabilitySchema = z.object({
  code: z.string(),
  module: z.string(),
  resource_type: z.string(),
  resource_code: z.string(),
  action: z.string(),
  display_name_zh: z.string(),
  risk_level: z.enum(["low", "medium", "high"]),
  dependencies: z.array(z.string()),
  resource_scope_kind: z.string(),
  assignable: z.boolean(),
})

export const adminBindingSchema = z.object({
  id: z.string().optional(),
  capability_code: z.string(),
  resource_type: z.string(),
  resource_code: z.string(),
  status: z.string().optional(),
})

export const roleScopeSchema = z.object({
  id: z.string().optional(),
  scope_key: z.string(),
  environment_id: z.string(),
  environment_code: z.string(),
  base_id: z.string().nullable().optional(),
  base_code: z.string().nullable().optional(),
  workshop_id: z.string().nullable().optional(),
  workshop_code: z.string().nullable().optional(),
})

export const roleApplicationAccessSchema = z.object({
  id: z.string(),
  application_id: z.string(),
  application_code: z.string(),
  application_name: z.string(),
  status: z.string(),
  capability_codes: z.array(z.string()),
  scopes: z.array(roleScopeSchema),
})

export const roleMemberSchema = z.object({
  id: z.string(),
  username: z.string(),
  display_name: z.string(),
  email: z.string(),
  status: z.string(),
  account_type: z.enum(["human", "service"]),
  membership_id: z.string(),
  membership_status: z.string(),
  membership_revision: z.number(),
  expires_at: z.string().nullable().optional(),
  assigned_by: z.string().optional(),
  assignment_source: z.string().optional(),
})

export const roleDetailSchema = z.object({
  role: roleSchema,
  admin: z.object({
    revision: z.number(),
    bindings: z.array(adminBindingSchema),
    implicit_all: z.boolean(),
  }),
  business: z.object({
    revision: z.number(),
    applications: z.array(roleApplicationAccessSchema),
  }),
  membership: z.object({
    revision: z.number(),
    members: z.array(roleMemberSchema),
  }),
})

export const roleAuditSchema = z.object({
  items: z.array(
    z.object({
      id: z.string(),
      event_type: z.string(),
      actor_id: z.string().nullable().optional(),
      status: z.string(),
      created_at: z.string(),
      action_zh: z.string(),
    }),
  ),
  notice: z.string(),
})

export const catalogApplicationSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  description: z.string(),
  project_code: z.string(),
  status: z.string(),
  capabilities: z.array(
    z.object({
      capability_code: z.string(),
      display_name_zh: z.string().default("只读业务能力"),
      version_constraint: z.string(),
    }),
  ),
})

export const workshopSchema = z.object({
  id: z.string(),
  code: z.string(),
  display_name: z.string(),
  status: z.string(),
})

export const baseSchema = z.object({
  id: z.string(),
  code: z.string(),
  display_name: z.string(),
  engine: z.string(),
  status: z.string(),
  workshops: z.array(workshopSchema),
})

export const environmentSchema = z.object({
  id: z.string(),
  code: z.string(),
  display_name: z.string(),
  status: z.string(),
  bases: z.array(baseSchema),
})

export type Role = z.infer<typeof roleSchema>
export type RoleDetail = z.infer<typeof roleDetailSchema>
export type AdminCapability = z.infer<typeof adminCapabilitySchema>
export type CatalogApplication = z.infer<typeof catalogApplicationSchema>
export type CatalogEnvironment = z.infer<typeof environmentSchema>

export type CreateRoleInput = {
  code: string
  name: string
  description: string
  purpose_tags: string[]
  copy_from_role_id?: string
}

export type ExplanationInput = {
  user_id: string
  application_id: string
  capability_code: string
  environment: string
  base: string
  workshop: string
  stage: "invoke" | "worker_start" | "tool_call" | "delivery"
}
