import { z } from "zod"

const validation = z.object({
  machine_valid: z.boolean().optional(),
  activation_blocked: z.boolean().optional(),
  business_verified: z.boolean().optional(),
  continuity: z
    .object({
      complete: z.boolean(),
      missing_keys: z.array(z.string()),
      confirmed_absences: z.array(z.string()),
    })
    .passthrough()
    .optional(),
})
export const codeKnowledgeSchema = z.object({
  components: z.record(z.string(), z.string()),
  sources: z.array(
    z.object({
      source_id: z.string(),
      knowledge_base_id: z.string(),
      display_name: z.string(),
      config_revision: z.number(),
      active_snapshot_id: z.string().nullable(),
      collected_revision: z.number().nullable(),
      collected_from_revision: z.number().nullable(),
      svn_verified: z.boolean(),
      enabled: z.number(),
      demand_enabled: z.number(),
      next_run_at: z.string().nullable(),
      plan: z.object({
        revision: z.number().optional(),
        application_publication_id: z.string().optional(),
        service_account_id: z.string().optional(),
        schedule: z
          .object({
            enabled: z.boolean(),
            local_time: z.string(),
            timezone: z.string(),
          })
          .optional(),
        sites: z
          .record(
            z.string(),
            z.object({
              snapshot_id: z.string(),
              revision: z.number(),
              updated_at: z.string(),
            })
          )
          .optional(),
      }),
      collection: z.object({
        state: z.string().optional(),
        target_revision: z.number().optional(),
        error_code: z.string().nullable().optional(),
        baseline_mapping: z
          .object({ state: z.string() })
          .passthrough()
          .optional(),
      }),
    })
  ),
  source_snapshots: z.array(
    z.object({
      id: z.string(),
      source_id: z.string(),
      source_kind: z.enum(["local_bundle", "svn"]),
      svn_revision: z.number().nullable(),
      created_at: z.string(),
      retired_at: z.string().nullable(),
    })
  ),
  builds: z.array(
    z.object({
      id: z.string(),
      source_id: z.string(),
      source_snapshot_id: z.string(),
      snapshot_id: z.string(),
      purpose: z.string(),
      stage: z.string(),
      active: z.number(),
      error_code: z.string().nullable(),
      created_at: z.string(),
      updated_at: z.string(),
      processing_hash: z.string(),
      unit_count: z.number(),
      validated_units: z.number(),
      validation,
    })
  ),
  partial: z.boolean(),
  history_checks: z.array(
    z.object({
      source_id: z.string(),
      document_id: z.string(),
      from_revision: z.number(),
      to_revision: z.number(),
      ledger_complete: z.number(),
      complete: z.boolean(),
      checked_count: z.number(),
      unresolved_count: z.number(),
    })
  ),
  demands: z.array(
    z.object({
      id: z.string(),
      source_id: z.string(),
      revision: z.number(),
      state: z.string(),
      build_id: z.string().nullable(),
      created_at: z.string(),
    })
  ),
})
const stateResult = z.object({
  mode: z.enum(["state", "unchanged", "unknown"]),
  state_key: z.string().nullable(),
  description: z.string(),
})
const transition = z.object({
  machine_key: z.string(),
  event_key: z.string(),
  from_state: z.object({
    mode: z.enum(["states", "any", "unresolved"]),
    state_keys: z.array(z.string()),
    description: z.string(),
  }),
  to_state: stateResult,
  actions: z.array(
    z.object({ key: z.string(), description: z.string(), phase: z.string() })
  ),
  failures: z.array(
    z.object({
      key: z.string(),
      condition: z.unknown(),
      phase: z.string(),
      outcome: z.string(),
      state_after: stateResult.extend({
        mode: z.enum(["state", "unchanged", "unknown", "indeterminate"]),
      }),
      retained_action_keys: z.array(z.string()),
      description: z.string(),
    })
  ),
})
export const codeDetailSchema = z.object({
  review_digest: z.string(),
  build_id: z.string(),
  snapshot_id: z.string(),
  relations: z.array(
    z.object({
      id: z.string(),
      from_key: z.string(),
      to_key: z.string(),
      kind: z.string(),
      required: z.boolean(),
      reading_mode: z.string(),
      read_at: z.string(),
    })
  ),
  units: z.array(
    z.object({
      id: z.string(),
      unit_key: z.string(),
      state: z.string(),
      job_id: z.string().nullable(),
      error_code: z.string().nullable(),
      result: z
        .object({
          replacement_unit_id: z.string().optional(),
          removed_keys: z
            .array(
              z.object({
                business_key: z.string(),
                evidence_ids: z.array(z.string()),
              })
            )
            .optional(),
          removal_evidence: z
            .array(
              z.object({
                id: z.string(),
                path: z.string(),
                symbol: z.string(),
                start_line: z.number(),
                end_line: z.number(),
              })
            )
            .optional(),
        })
        .passthrough(),
    })
  ),
  records: z.array(
    z.object({
      knowledge_id: z.string(),
      revision_id: z.string(),
      knowledge: z
        .object({
          title: z.string(),
          object_key: z.string(),
          transition: transition.nullable(),
          states: z.array(
            z.object({
              key: z.string(),
              name: z.string(),
              raw_value: z.string(),
            })
          ),
          summary: z.string(),
          role: z.string(),
          coverage: z.string(),
        })
        .passthrough(),
      evidence: z.array(
        z.object({
          path: z.string(),
          symbol: z.string(),
          start_line: z.number(),
          end_line: z.number(),
        })
      ),
    })
  ),
  has_more: z.boolean(),
  next_cursor: z.string().nullable(),
})
export type CodeKnowledge = z.infer<typeof codeKnowledgeSchema>
export type CodeBuild = CodeKnowledge["builds"][number]
export type CodeSource = CodeKnowledge["sources"][number]
export type CodeDetail = z.infer<typeof codeDetailSchema>
export const codeStage: Record<string, string> = {
  QUEUED: "等待提取",
  SOURCE_READY: "源码已就绪",
  EXTRACTING: "正在提取",
  VALIDATING: "等待业务核验",
  INDEXING: "正在建立索引",
  READY: "版本可查询",
  ACTIVATED: "已设为开发快照",
  FAILED: "失败",
  INTERRUPTED: "已中断",
  CANCELLED: "已取消",
}
export type CodeCommand =
  | {
      action: "plan"
      id: string
      input: {
        expected_plan_revision: number
        application_publication_id: string
        service_account_id: string
        schedule_enabled: boolean
        demand_enabled: boolean
        local_time: string
        timezone: string
      }
    }
  | { action: "version"; id: string; input: { revision: number } }
  | {
      action: "site"
      id: string
      input: {
        site_id: string
        snapshot_id: string
        expected_plan_revision: number
      }
    }
  | { action: "retry_source"; id: string }
  | {
      action: "start"
      input: {
        source_id: string
        source_snapshot_id: string
        application_publication_id: string
        service_account_id: string
      }
    }
  | {
      action: "review"
      id: string
      input: {
        review_reference: string
        processing_hash: string
        candidate_digest: string
        checked_unit_ids: string[]
      }
    }
  | { action: "retry"; id: string }
  | {
      action: "rollback"
      id: string
      input: { snapshot_id: string; expected_current: string }
    }
