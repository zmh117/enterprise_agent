import { z } from "zod"

const metrics = z.object({
  created: z.number(),
  revised: z.number(),
  unchanged: z.number(),
  stale: z.number(),
  completed: z.number(),
  failed: z.number(),
  total: z.number(),
})
export const planConfigurationSchema = z.object({
  code: z.string(),
  source_code: z.string(),
  expected_revision: z.number(),
  configuration: z.object({
    base_codes: z.record(z.string(), z.string()),
    resource_ids: z.array(z.string()),
    collector: z
      .object({
        provider_origin: z.string(),
        team_id: z.string(),
        project_ids: z.array(z.string()),
        credential_ref: z.string(),
        first_date: z.string(),
        issue_types: z.record(z.string(), z.array(z.string())),
        child_type_ids: z.array(z.string()),
      })
      .optional(),
  }),
})
export const operationSchema = z.object({
  id: z.string(),
  kind: z.enum(["build", "up", "stop", "sync", "backfill"]),
  binding_id: z.string().nullable(),
  state: z.string(),
  stage: z.string(),
  run_id: z.string().nullable(),
  attempts: z.number(),
  error_code: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  parameters: z.object({
    first_day: z.string().optional(),
    last_day: z.string().optional(),
    binding_revision: z.number().optional(),
  }),
})
export const planSchema = z.object({
  id: z.string(),
  code: z.string(),
  revision: z.number(),
  enabled: z.boolean(),
  schedule_enabled: z.boolean(),
  interval_seconds: z.number(),
  next_run_at: z.string().nullable(),
  last_success_at: z.string().nullable(),
  first_day: z.string().nullable(),
  bases: z.array(
    z.object({
      kind: z.string(),
      code: z.string(),
      knowledge_base_id: z.string(),
      metrics: metrics.nullable(),
    })
  ),
  run: z
    .object({
      run_id: z.string(),
      phase: z.string(),
      active: z.boolean(),
      error_code: z.string().nullable(),
      updated_at: z.string(),
      documents: z
        .object({
          total: z.number(),
          completed: z.number(),
          failed: z.number(),
        })
        .optional(),
      progress: z
        .object({
          phase: z.string(),
          processed: z.number().optional(),
          total: z.number().optional(),
          encoded: z.number().optional(),
          reused: z.number().optional(),
        })
        .nullable(),
      collection: z
        .object({
          mode: z.string(),
          first_day: z.string(),
          last_day: z.string(),
          next_day: z.string().nullable().optional(),
          completed_days: z.number(),
          total_days: z.number(),
        })
        .optional(),
    })
    .nullable(),
})
const runtime = z.object({
  online: z.boolean(),
  observed_at: z.string().nullable(),
  snapshot: z.object({
    services: z
      .array(
        z.object({ name: z.string(), state: z.string(), health: z.string() })
      )
      .optional(),
    error_code: z.string().nullable().optional(),
    built_version: z.string().optional(),
    running_version: z.string().optional(),
    operation_id: z.string().nullable().optional(),
  }),
})
export const operationsSchema = z.object({
  controller: runtime,
  sync_worker: runtime,
  deployment: runtime,
  plans: z.array(planSchema),
  operations: z.array(operationSchema),
})
export const eventsSchema = z.object({
  events: z.array(
    z.object({
      id: z.string(),
      operation_id: z.string().nullable(),
      service: z.string(),
      code: z.string(),
      created_at: z.string(),
      details: z.record(z.string(), z.union([z.string(), z.number()])),
    })
  ),
  cursor: z.string().nullable(),
})
export type KnowledgePlan = z.infer<typeof planSchema>
export type KnowledgeOperation = z.infer<typeof operationSchema>
export type KnowledgeOperationsSnapshot = z.infer<typeof operationsSchema>
export type OperationRequest = {
  kind: KnowledgeOperation["kind"]
  request_key: string
  binding_id?: string
  first_day?: string
  last_day?: string
}

export const operationNames: Record<string, string> = {
  build: "构建镜像",
  up: "启动 / 应用版本",
  stop: "停止服务",
  sync: "立即同步",
  backfill: "日期补采",
}
export const phaseNames: Record<string, string> = {
  QUEUED: "排队中",
  RUNNING: "执行中",
  RETRY_WAIT: "等待重试",
  SUCCEEDED: "完成",
  PARTIAL: "部分失败",
  FAILED: "失败",
  INTERRUPTED: "已中断",
  COLLECTING: "采集中",
  STAGED: "待处理",
  CHUNKING: "分块与向量处理",
  INDEXING: "索引核验",
  VERIFIED: "清理完成",
  ACTIVATED: "完成",
  queued: "排队中",
  started: "开始执行",
  completed: "完成",
  failed: "失败",
  interrupted: "已中断",
  retry_pending: "等待重试",
  preflight: "检查配置与依赖",
  building: "构建镜像",
  build_step: "镜像构建步骤",
  models: "准备模型",
  starting: "启动服务",
  ready: "已就绪",
  stopping_sync: "保存同步断点并停止",
  stopping_services: "停止检索及存储服务",
  stopped: "已停止",
  reconciled: "已核对服务状态",
  sync_progress: "文档处理进度",
  sync_event: "同步事件",
  schedule_changed: "自动同步设置已更新",
  running: "运行中",
  exited: "已停止",
  absent: "未创建",
  created: "待启动",
  restarting: "重启中",
  paused: "已暂停",
  dead: "异常",
  unknown: "未知",
  healthy: "就绪",
  unhealthy: "异常",
}
export const serviceNames: Record<string, string> = {
  "knowledge-qdrant": "向量存储",
  "knowledge-embedding": "后台模型",
  "knowledge-embedding-online": "检索向量模型",
  "knowledge-reranker": "重排模型",
  "knowledge-mcp": "检索服务",
  "knowledge-sync": "同步进程",
  "knowledge-model-prepare": "向量模型准备",
  "knowledge-reranker-prepare": "重排模型准备",
  sync: "采集计划",
  controller: "运维执行器",
}
export function displayTime(value: string | null | undefined) {
  return value
    ? new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : "—"
}
