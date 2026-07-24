import { z } from "zod"

export const runtimeJobSchema = z
  .object({
    id: z.string(),
    session_id: z.string(),
    status: z.string(),
    internal_user_id: z.string().nullish().transform((value) => value ?? ""),
    project_code: z.string().default(""),
    source_channel: z.string().default(""),
    source_connector_id: z.string().default(""),
    agent_code: z.string().default(""),
    correlation_id: z.string().default(""),
    business_application_id: z.string().nullish().transform((value) => value ?? ""),
    business_application_code: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    business_application_publication_id: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    business_application_deployment_id: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    business_application_route_id: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    business_application_runtime_status: z
      .string()
      .default("legacy_unattributed"),
    business_application_route_decision: z
      .record(z.string(), z.unknown())
      .default({}),
    error_summary: z.string().default(""),
    created_at: z.string(),
    started_at: z.string().nullish(),
    finished_at: z.string().nullish(),
  })
  .passthrough()

export const runtimeJobPageSchema = z.object({
  items: z.array(runtimeJobSchema),
  page: z
    .object({
      limit: z.number(),
      has_more: z.boolean(),
      next_cursor: z.string().nullable().optional(),
    })
    .passthrough(),
})

export const runtimeJobDetailSchema = z
  .object({
    job: runtimeJobSchema,
    session_ref: z.object({ id: z.string() }),
    steps: z.array(z.record(z.string(), z.unknown())).default([]),
    tool_calls: z.array(z.record(z.string(), z.unknown())).default([]),
    delivery_attempts: z.array(z.record(z.string(), z.unknown())).default([]),
    webhook_events: z.array(z.record(z.string(), z.unknown())).default([]),
  })
  .passthrough()

export const conversationDetailSchema = z
  .object({
    session: z
      .object({
        id: z.string(),
        requester_id: z.string().default(""),
        source_channel: z.string().default(""),
        source_connector_id: z.string().default(""),
        external_conversation_id: z.string().default(""),
        business_application_id: z
          .string()
          .nullish()
          .transform((value) => value ?? ""),
        business_application_code: z
          .string()
          .nullish()
          .transform((value) => value ?? ""),
        conversation_mode: z.string().default("legacy"),
        recent_message_limit: z.number().nullable().optional(),
        created_at: z.string().default(""),
        updated_at: z.string().default(""),
      })
      .passthrough(),
    jobs: z.array(runtimeJobSchema).default([]),
    messages: z.array(z.record(z.string(), z.unknown())).default([]),
  })
  .passthrough()

export type RuntimeJob = z.infer<typeof runtimeJobSchema>
