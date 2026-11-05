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
          verified: z.number().optional(),
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
const buildActionNames: Record<string, string> = {
  load_build_definition: "读取镜像构建配置",
  load_build_context: "读取构建文件",
  load_ignore_rules: "读取构建文件排除规则",
  load_image_metadata: "读取基础镜像信息",
  registry_auth: "验证镜像仓库访问权限",
  prepare_base_image: "准备基础镜像",
  copy_dependency_manifests: "复制依赖清单",
  copy_model_configuration: "复制模型配置与版本清单",
  copy_application_code: "复制服务代码",
  copy_files: "复制构建文件",
  install_python_dependencies: "安装 Python 依赖",
  install_system_packages: "安装系统依赖",
  configure_runtime_user: "配置容器运行用户",
  configure_permissions: "设置文件访问权限",
  run_python_script: "执行 Python 构建脚本",
  run_build_command: "执行镜像构建命令",
  configure_workdir: "设置容器工作目录",
  configure_environment: "配置运行环境",
  configure_entrypoint: "配置服务启动方式",
  configure_image: "配置镜像属性",
  export_image: "导出构建镜像",
  resolve_provenance: "生成镜像构建来源信息",
  other_build_step: "执行其他构建操作",
}
export function buildStepLines(
  details: Record<string, string | number>
): string[] {
  const step =
    typeof details.step === "number" ? `步骤 ${details.step}` : "构建步骤"
  const action =
    typeof details.build_action === "string"
      ? (buildActionNames[details.build_action] ?? "未识别的构建操作")
      : "此历史记录未保存具体操作"
  const lines = [`${step}：${action}`]
  const { stage_step: current, stage_total: total } = details
  if (
    typeof current === "number" &&
    typeof total === "number" &&
    current > 0 &&
    current <= total
  ) {
    lines.push(`当前构建阶段：第 ${current} / ${total} 步`)
  }
  return lines
}
export function vectorProgressSummary(
  progress: NonNullable<NonNullable<KnowledgePlan["run"]>["progress"]>
): string {
  const completed = progress.processed ?? progress.verified
  const counts =
    completed !== undefined && progress.total !== undefined
      ? `已完成 ${completed} / ${progress.total} 块`
      : [
          completed === undefined
            ? "已完成块数待上报"
            : `已完成 ${completed} 块`,
          progress.total === undefined
            ? "总块数待上报"
            : `总计 ${progress.total} 块`,
        ].join(" · ")
  return [
    counts,
    ...(progress.encoded === undefined
      ? []
      : [`新生成向量 ${progress.encoded} 块`]),
    ...(progress.reused === undefined
      ? []
      : [`复用已有向量 ${progress.reused} 块`]),
  ].join(" · ")
}
export function displayTime(value: string | null | undefined) {
  return value
    ? new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : "—"
}
