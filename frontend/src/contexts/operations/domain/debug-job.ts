import { z } from "zod"

const executionScopeSchema = z
  .object({
    id: z.string(),
    scope_key: z.string(),
    environment_code: z.string(),
    base_code: z.string().default(""),
    workshop_code: z.string().default(""),
  })
  .passthrough()

const deliveryBindingSchema = z
  .object({
    binding_id: z.string(),
    binding_order: z.number().int().nonnegative(),
    delivery_type: z.string(),
    connector_id: z.string(),
  })
  .passthrough()

const debugApplicationSchema = z
  .object({
    id: z.string(),
    code: z.string(),
    name: z.string(),
    project_code: z.string(),
    publication_id: z.string(),
    publication_revision: z.number().int().positive(),
    execution_scopes: z.array(executionScopeSchema),
    delivery_bindings: z.array(deliveryBindingSchema),
  })
  .passthrough()

export const debugOptionsSchema = z.object({
  environment: z.string(),
  default_delivery: z.object({
    type: z.literal("none"),
    binding_id: z.literal(""),
  }),
  applications: z.array(debugApplicationSchema),
})

export const debugJobCreateResponseSchema = z.object({
  accepted: z.literal(true),
  status: z.string(),
  job_id: z.string(),
  idempotency_key: z.string(),
})

export type DebugOptions = z.infer<typeof debugOptionsSchema>
export type DebugApplication = z.infer<typeof debugApplicationSchema>
