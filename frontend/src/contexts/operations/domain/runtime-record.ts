import { z } from "zod"

const executionPolicyValuesSchema = z.object({
  max_turns: z.number().int(),
  timeout_seconds: z.number().int(),
  max_tool_calls: z.number().int(),
})

const jobExecutionPolicySchema = z.object({
  schema_version: z.literal(1),
  requested: executionPolicyValuesSchema,
  effective: executionPolicyValuesSchema,
  sources: z.record(z.string(), z.string()),
})

const nullableCounterSchema = z.number().int().nonnegative().nullable()

const executionSummarySchema = z.object({
  accounting_status: z.enum(["COMPLETE", "PARTIAL", "UNAVAILABLE"]),
  observed_model_turn_count: z.number().int().nonnegative().default(0),
  api_retry_count: z.number().int().nonnegative().default(0),
  runtime_invocation_count: z.number().int().nonnegative().default(0),
  total_duration_ms: nullableCounterSchema,
  total_api_duration_ms: nullableCounterSchema,
  input_tokens: nullableCounterSchema,
  output_tokens: nullableCounterSchema,
  cache_creation_input_tokens: nullableCounterSchema,
  cache_read_input_tokens: nullableCounterSchema,
  model_usage: z.array(z.record(z.string(), z.unknown())).default([]),
  models: z.array(z.string()).default([]),
  estimated_cost_usd: z.string().nullable(),
  execution_status: z.enum(["SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"]),
  delivery_status: z.string().default("NOT_REQUESTED"),
  execution_failure_stage: z.string().nullable(),
  display_failure_stage: z.string().nullable(),
  failure_code: z.string().nullable(),
  failure_summary: z.string().nullable(),
  retry_exhausted: z.boolean().default(false),
  source_protocol_version: z.string().default("1.4"),
})

const unavailableExecutionSummary = {
  accounting_status: "UNAVAILABLE" as const,
  observed_model_turn_count: 0,
  api_retry_count: 0,
  runtime_invocation_count: 0,
  total_duration_ms: null,
  total_api_duration_ms: null,
  input_tokens: null,
  output_tokens: null,
  cache_creation_input_tokens: null,
  cache_read_input_tokens: null,
  model_usage: [],
  models: [],
  estimated_cost_usd: null,
  execution_status: "UNKNOWN" as const,
  delivery_status: "NOT_REQUESTED",
  execution_failure_stage: null,
  display_failure_stage: null,
  failure_code: null,
  failure_summary: null,
  retry_exhausted: false,
  source_protocol_version: "1.4",
}

const buildIdentitySchema = z.object({
  component: z.string(),
  source_revision: z.string(),
  build_id: z.string(),
  platform: z.string(),
  image_digest: z.string().optional(),
})

const toolContractSummarySchema = z.object({
  status: z.enum(["MATCH", "DRIFT", "NOT_OBSERVED"]),
  last_invocation_id: z.string().default(""),
  observation_hash: z.string().default(""),
  prompt_template_version: z.string().default(""),
  prompt_contract_hash: z.string().default(""),
  component_build_identities: z.array(buildIdentitySchema).default([]),
})

const unavailableToolContractSummary = {
  status: "NOT_OBSERVED" as const,
  last_invocation_id: "",
  observation_hash: "",
  prompt_template_version: "",
  prompt_contract_hash: "",
  component_build_identities: [],
}

export const runtimeJobSchema = z
  .object({
    id: z.string(),
    session_id: z.string(),
    status: z.string(),
    internal_user_id: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    user_username: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    user_display_name: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    project_code: z.string().default(""),
    source_channel: z.string().default(""),
    source_connector_id: z.string().default(""),
    source_connector_name: z.string().default(""),
    source_connector_availability: z
      .enum([
        "AVAILABLE",
        "UNAVAILABLE",
        "UNAVAILABLE_HISTORICAL",
        "UNKNOWN",
        "NOT_APPLICABLE",
      ])
      .default("UNKNOWN"),
    agent_code: z.string().default(""),
    correlation_id: z.string().default(""),
    business_application_id: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    business_application_code: z
      .string()
      .nullish()
      .transform((value) => value ?? ""),
    business_application_name: z
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
    execution_policy: jobExecutionPolicySchema,
    tool_call_count: z.number().int().nonnegative().default(0),
    execution_policy_exhausted: z.boolean().default(false),
    execution_summary: executionSummarySchema.default(
      unavailableExecutionSummary
    ),
    tool_contract: toolContractSummarySchema.default(
      unavailableToolContractSummary
    ),
    last_error_code: z.string().default(""),
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

const deliveryEventSchema = z
  .object({
    id: z.string(),
    job_id: z.string(),
    result_artifact_id: z.string(),
    application_publication_id: z.string().default(""),
    route_type: z.string().default("none"),
    connector_id: z.string().default(""),
    delivery_kind: z.string().default("result"),
    target_summary: z.record(z.string(), z.unknown()).default({}),
    correlation_id: z.string().default(""),
    status: z.string(),
    attempt_count: z.number().int().nonnegative(),
    max_attempts: z.number().int().positive(),
    replay_count: z.number().int().nonnegative(),
    max_replay_count: z.number().int().nonnegative(),
    next_attempt_at: z.string(),
    last_error_code: z.string().default(""),
    last_error_summary: z.string().default(""),
    started_at: z.string().nullish(),
    finished_at: z.string().nullish(),
    dead_at: z.string().nullish(),
    last_replayed_at: z.string().nullish(),
    created_at: z.string(),
    updated_at: z.string(),
    terminal: z.boolean(),
    delivered: z.boolean(),
  })
  .passthrough()

const deliveryAttemptSchema = z
  .object({
    id: z.string(),
    job_id: z.string(),
    delivery_outbox_id: z.string().nullish(),
    replay_no: z.number().int().nonnegative().default(0),
    attempt_no: z.number().int().nonnegative(),
    route_type: z.string().default("none"),
    connector_id: z.string().default(""),
    target_summary: z.record(z.string(), z.unknown()).default({}),
    correlation_id: z.string().default(""),
    status: z.string(),
    error_code: z.string().default(""),
    error_message: z.string().nullish(),
    created_at: z.string(),
    finished_at: z.string().nullish(),
  })
  .passthrough()

const deliveryChunkSchema = z
  .object({
    id: z.string(),
    attempt_id: z.string(),
    delivery_outbox_id: z.string().nullish(),
    replay_no: z.number().int().nonnegative().default(0),
    attempt_no: z.number().int().nonnegative(),
    chunk_index: z.number().int().positive(),
    chunk_count: z.number().int().positive(),
    status: z.string(),
    payload_summary: z.record(z.string(), z.unknown()).default({}),
    error_message: z.string().nullish(),
    created_at: z.string(),
    sent_at: z.string().nullish(),
  })
  .passthrough()

const deliveryTimelineSchema = z.object({
  events: z.array(deliveryEventSchema).default([]),
  attempts: z.array(deliveryAttemptSchema).default([]),
  chunks: z.array(deliveryChunkSchema).default([]),
})

const jobDispatchSchema = z
  .object({
    id: z.string(),
    job_id: z.string(),
    correlation_id: z.string().default(""),
    status: z.string(),
    attempt_count: z.number().int().nonnegative(),
    max_attempts: z.number().int().positive(),
    replay_count: z.number().int().nonnegative(),
    max_replay_count: z.number().int().nonnegative(),
    next_attempt_at: z.string(),
    last_error_code: z.string().default(""),
    last_error_summary: z.string().default(""),
    created_at: z.string().default(""),
    updated_at: z.string().default(""),
  })
  .passthrough()

const modelCallSchema = z
  .object({
    id: z.string(),
    job_id: z.string(),
    invocation_id: z.string(),
    request_digest: z.string(),
    runtime_sequence: z.number().int().positive(),
    provider_request_id: z.string().nullable(),
    provider_message_id: z.string().nullable(),
    model_id: z.string(),
    status: z.enum(["SUCCEEDED", "FAILED"]),
    started_at: z.string().nullable(),
    completed_at: z.string(),
    duration_ms: nullableCounterSchema,
    duration_source: z.enum(["SDK_OBSERVED", "UNAVAILABLE"]),
    input_tokens: nullableCounterSchema,
    output_tokens: nullableCounterSchema,
    cache_creation_input_tokens: nullableCounterSchema,
    cache_read_input_tokens: nullableCounterSchema,
    stop_reason: z.string().nullable(),
    error_code: z.string().nullable(),
    error_summary: z.string().nullable(),
  })
  .passthrough()

export const modelCallPageSchema = z.object({
  items: z.array(modelCallSchema).default([]),
  limit: z.number().int().positive().default(50),
  has_more: z.boolean().default(false),
  next_cursor: z.string().nullable().default(null),
})

const TEXT_FILE_FORMAT_CODES = ["TXT", "LOG", "MARKDOWN"] as const
const DOCUMENT_FILE_FORMAT_CODES = [
  "PDF",
  "DOCX",
  "PPTX",
  "XLSX",
  "PNG",
  "JPEG",
  "WEBP",
] as const

const fileWorkspaceSchema = z.object({
  enabled: z.boolean(),
  manifest_schema_version: z.number().int().nullable(),
  formats: z.array(
    z.object({
      format_code: z.string().min(1).max(32),
      file_count: z.number().int().nonnegative(),
      allowed_actions: z.array(z.string()),
    })
  ),
  output_commits: z
    .array(
      z.object({
        format_code: z.string().min(1).max(32),
        status: z.string().min(1).max(32),
        commit_count: z.number().int().nonnegative(),
      })
    )
    .default([]),
})

const frozenToolContractEntrySchema = z.object({
  server_code: z.string(),
  tool_name: z.string(),
  schema_hash: z.string(),
})

const liveToolContractEntrySchema = frozenToolContractEntrySchema.extend({
  status: z.string(),
})

const effectiveToolContractEntrySchema = frozenToolContractEntrySchema.extend({
  sdk_tool_name: z.string(),
  origin: z.enum(["frozen_mcp", "runtime_derived", "sdk_builtin"]),
  authorization_status: z.string(),
  dependency_tool_name: z.string().optional(),
})

const toolContractObservationSchema = z.object({
  invocation_id: z.string(),
  request_digest: z.string(),
  sequence: z.number().int().positive(),
  created_at: z.string(),
  status: z.enum(["MATCH", "DRIFT", "NOT_OBSERVED"]),
  observation_hash: z.string(),
  snapshot_hash: z.string(),
  component_build_identities: z.array(buildIdentitySchema),
  job_frozen: z.array(frozenToolContractEntrySchema),
  file_mcp_live: z.object({
    status: z.string(),
    toolset_hash: z.string(),
    build_identity: buildIdentitySchema.or(z.object({})),
    tools: z.array(liveToolContractEntrySchema),
  }),
  runtime_effective: z.array(effectiveToolContractEntrySchema),
  prompt: z.object({
    template_version: z.string(),
    contract_hash: z.string(),
    declared_tools: z.array(z.string()),
  }),
  matrix: z.array(
    z.object({
      server_code: z.string(),
      tool_name: z.string(),
      status: z.string(),
    })
  ),
})

const toolContractEvidenceSchema = z.object({
  summary: toolContractSummarySchema,
  snapshot: z
    .object({
      id: z.string(),
      schema_version: z.number().int(),
      snapshot_hash: z.string(),
      created_at: z.string(),
      tools: z.array(frozenToolContractEntrySchema),
    })
    .nullable(),
  observations: z.array(toolContractObservationSchema),
  notice: z.string(),
})

export const runtimeJobDetailSchema = z
  .object({
    job: runtimeJobSchema,
    session_ref: z.object({ id: z.string() }),
    dispatch: jobDispatchSchema.nullish(),
    steps: z.array(z.record(z.string(), z.unknown())).default([]),
    tool_calls: z.array(z.record(z.string(), z.unknown())).default([]),
    execution_summary: executionSummarySchema.default(
      unavailableExecutionSummary
    ),
    model_calls: modelCallPageSchema.default({
      items: [],
      limit: 50,
      has_more: false,
      next_cursor: null,
    }),
    mcp_operation_links: z.array(z.record(z.string(), z.string())).default([]),
    file_workspace: fileWorkspaceSchema.default({
      enabled: false,
      manifest_schema_version: null,
      formats: [],
      output_commits: [],
    }),
    tool_contract: toolContractEvidenceSchema.default({
      summary: unavailableToolContractSummary,
      snapshot: null,
      observations: [],
      notice: "尚无工具契约观测；NOT_OBSERVED 不代表健康。",
    }),
    deliveries: deliveryTimelineSchema,
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

const documentProcessingRunSchema = z.object({
  run_id: z.string(),
  source_version_id: z.string(),
  tenant_id: z.string(),
  job_id: z.string(),
  application_id: z.string(),
  application_code: z.string(),
  publication_id: z.string(),
  profile_code: z.string(),
  profile_hash: z.string(),
  status: z.string(),
  attempt: z.number().int().nonnegative(),
  error_code: z.string(),
  page_count: z.number().int().nonnegative().nullable(),
  processing_time_ms: z.number().int().nonnegative().nullable(),
  updated_at: z.string(),
})

const documentProcessingOperationsSchema = z.object({
  groups: z
    .array(
      z.object({
        tenant_id: z.string(),
        application_id: z.string(),
        application_code: z.string(),
        publication_id: z.string(),
        profile_code: z.string(),
        status: z.string(),
        count: z.number().int().nonnegative(),
        total_attempts: z.number().int().nonnegative(),
        source_size_bytes: z.number().int().nonnegative(),
        output_size_bytes: z.number().int().nonnegative(),
        earliest_created_at: z.string(),
        latest_updated_at: z.string(),
      })
    )
    .default([]),
  recent_failures: z.array(documentProcessingRunSchema).default([]),
  traces: z
    .array(
      documentProcessingRunSchema.extend({
        processor_code: z.string(),
        processor_version: z.string(),
        processor_build_digest: z.string(),
        source_size_bytes: z.number().int().nonnegative(),
        created_at: z.string(),
        representations: z
          .array(
            z.object({
              representation_id: z.string(),
              source_version_id: z.string(),
              kind: z.string(),
              media_type: z.string(),
              status: z.string(),
              size_bytes: z.number().int().nonnegative(),
              content_sha256: z.string(),
              profile_hash: z.string(),
              created_at: z.string(),
              content_deleted_at: z.string(),
            })
          )
          .default([]),
      })
    )
    .default([]),
})

export const fileOperationsSchema = z.object({
  file_service: z.object({
    configured: z.boolean(),
    ready: z.boolean(),
    reason_code: z.string(),
  }),
  file_worker: z.object({
    configured: z.boolean(),
    ready: z.boolean(),
    reason_code: z.string(),
    attachment_queue: z.object({
      availability: z.string(),
      ready: z.number().int().nonnegative().nullable(),
      unacked: z.number().int().nonnegative().nullable(),
      consumers: z.number().int().nonnegative().nullable(),
    }),
  }),
  document_processing: z.object({
    configured: z.boolean(),
    ready: z.boolean(),
    reason_code: z.string(),
    file_processing_worker: z.object({
      configured: z.boolean(),
      ready: z.boolean(),
      reason_code: z.string(),
      components: z.object({
        rabbitmq: z.enum(["ready", "unavailable"]),
        file_service: z.enum(["ready", "unavailable"]),
        docling: z.enum(["ready", "unavailable"]),
      }),
    }),
    queues: z.object({
      processing: z.object({
        availability: z.string(),
        ready: z.number().int().nonnegative().nullable(),
        unacked: z.number().int().nonnegative().nullable(),
        consumers: z.number().int().nonnegative().nullable(),
      }),
      retry: z.object({
        availability: z.string(),
        ready: z.number().int().nonnegative().nullable(),
        unacked: z.number().int().nonnegative().nullable(),
        consumers: z.number().int().nonnegative().nullable(),
      }),
      dead: z.object({
        availability: z.string(),
        ready: z.number().int().nonnegative().nullable(),
        unacked: z.number().int().nonnegative().nullable(),
        consumers: z.number().int().nonnegative().nullable(),
      }),
    }),
    operations: documentProcessingOperationsSchema.default({
      groups: [],
      recent_failures: [],
      traces: [],
    }),
  }),
  backlog: z.object({
    cleanup: z.number().int().nonnegative(),
    staging: z.number().int().nonnegative(),
    attachment: z.number().int().nonnegative(),
    workspace: z.number().int().nonnegative(),
    retained: z.number().int().nonnegative(),
    conflict: z.number().int().nonnegative(),
    domain_outbox: z.number().int().nonnegative(),
  }),
  earliest_due: z.string(),
  domain_outbox_earliest_created_at: z.string(),
  domain_outbox_failure_code: z.string(),
  recent_cleanup: z
    .object({
      status: z.string(),
      resource_type: z.string(),
      reason: z.string(),
      failure_code: z.string(),
      updated_at: z.string(),
    })
    .nullable(),
})

export type RuntimeJob = z.infer<typeof runtimeJobSchema>
export type ExecutionSummary = z.infer<typeof executionSummarySchema>
export type ModelCall = z.infer<typeof modelCallSchema>
export type ModelCallPage = z.infer<typeof modelCallPageSchema>
export type DeliveryEvent = z.infer<typeof deliveryEventSchema>
export type DeliveryAttempt = z.infer<typeof deliveryAttemptSchema>
export type DeliveryChunk = z.infer<typeof deliveryChunkSchema>
export type JobDispatch = z.infer<typeof jobDispatchSchema>
export type FileWorkspaceEvidence = z.infer<typeof fileWorkspaceSchema>
export type ToolContractEvidence = z.infer<typeof toolContractEvidenceSchema>
export type FileOperations = z.infer<typeof fileOperationsSchema>
export const TEXT_RUNTIME_FILE_FORMATS = TEXT_FILE_FORMAT_CODES
export const DOCUMENT_RUNTIME_FILE_FORMATS = DOCUMENT_FILE_FORMAT_CODES
