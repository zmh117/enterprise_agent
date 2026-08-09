import { z } from "zod"

const executionPolicySchema = z
  .object({
    schema_version: z.number().int().default(1),
    requested: z.record(z.string(), z.unknown()).default({}),
    effective: z.record(z.string(), z.unknown()).default({}),
    sources: z.record(z.string(), z.string()).default({}),
  })
  .default({ schema_version: 1, requested: {}, effective: {}, sources: {} })

export const runtimeJobSchema = z
  .object({
    id: z.string(),
    session_id: z.string(),
    status: z.string(),
    source_channel: z.string().default(""),
    source_connector_id: z.string().default(""),
    source_connector_name: z.string().default(""),
    agent_code: z.string().default("agent"),
    correlation_id: z.string().default(""),
    execution_policy: executionPolicySchema,
    tool_call_count: z.number().int().nonnegative().default(0),
    execution_policy_exhausted: z.boolean().default(false),
    last_error_code: z.string().default(""),
    error_summary: z.string().default(""),
    created_at: z.string(),
    started_at: z.string().nullish(),
    finished_at: z.string().nullish(),
  })
  .passthrough()

export const runtimeJobPageSchema = z.object({
  items: z.array(runtimeJobSchema),
  page: z.object({
    limit: z.number(),
    has_more: z.boolean(),
    next_cursor: z.string().nullable().optional(),
  }),
})

const mcpAttemptSchema = z.object({
  attempt: z.number().int().positive(),
  status: z.string(),
  error_code: z.string().default(""),
  duration_ms: z.number().int().nonnegative(),
  created_at: z.string(),
})

export const mcpToolCallSchema = z.object({
  id: z.string(),
  job_id: z.string(),
  mcp_server_code: z.enum(["ones-mcp", "data-mcp"]),
  server_version: z.string(),
  tool_name: z.string(),
  tool_schema_hash: z.string(),
  subject_snapshot_id: z.string().default(""),
  resource_deployment_id: z.string().default(""),
  resource_revision_id: z.string().default(""),
  credential_revision: z.number().int().nonnegative(),
  request_summary: z.record(z.string(), z.unknown()).default({}),
  result_hash: z.string().default(""),
  result_size: z.number().int().nonnegative(),
  status: z.string(),
  duration_ms: z.number().int().nonnegative(),
  correlation_id: z.string(),
  occurred_at: z.string(),
  attempts: z.array(mcpAttemptSchema).default([]),
})

const deliveryEventSchema = z
  .object({
    id: z.string(),
    status: z.string(),
    delivery_kind: z.string().default("result"),
    route_type: z.string().default("none"),
    attempt_count: z.number().int().nonnegative().default(0),
    last_error_code: z.string().default(""),
    last_error_summary: z.string().default(""),
    created_at: z.string(),
    updated_at: z.string().default(""),
  })
  .passthrough()

const deliveryAttemptSchema = z
  .object({
    id: z.string(),
    delivery_outbox_id: z.string().nullish(),
    attempt_no: z.number().int().nonnegative(),
    status: z.string(),
    error_code: z.string().default(""),
    created_at: z.string(),
  })
  .passthrough()

const deliveryChunkSchema = z.object({
  id: z.string(),
  delivery_outbox_id: z.string().nullish(),
  chunk_index: z.number().int().nonnegative(),
  chunk_count: z.number().int().positive(),
  status: z.string(),
  created_at: z.string(),
}).passthrough()

export const runtimeJobDetailSchema = z.object({
  job: runtimeJobSchema,
  session_ref: z.object({ id: z.string() }),
  dispatch: z.record(z.string(), z.unknown()).nullable(),
  steps: z.array(z.record(z.string(), z.unknown())).default([]),
  mcp_tool_calls: z.array(mcpToolCallSchema).default([]),
  deliveries: z.object({
    events: z.array(deliveryEventSchema).default([]),
    attempts: z.array(deliveryAttemptSchema).default([]),
    chunks: z.array(deliveryChunkSchema).default([]),
  }),
})

export const conversationDetailSchema = z.object({
  session: z.object({
    id: z.string(),
    requester_id: z.string(),
    source_channel: z.string().default(""),
    source_connector_id: z.string().default(""),
    external_conversation_id: z.string().default(""),
    created_at: z.string().default(""),
    updated_at: z.string().default(""),
  }),
  jobs: z.array(runtimeJobSchema).default([]),
  messages: z.array(z.record(z.string(), z.unknown())).default([]),
})

export type RuntimeJob = z.infer<typeof runtimeJobSchema>
export type McpToolCall = z.infer<typeof mcpToolCallSchema>
export type DeliveryEvent = z.infer<typeof deliveryEventSchema>
export type DeliveryAttempt = z.infer<typeof deliveryAttemptSchema>
export type DeliveryChunk = z.infer<typeof deliveryChunkSchema>
