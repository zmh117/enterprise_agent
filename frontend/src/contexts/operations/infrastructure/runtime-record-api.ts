import {
  conversationDetailSchema,
  modelCallPageSchema,
  runtimeJobDetailSchema,
  runtimeJobPageSchema,
} from "@/contexts/operations/domain/runtime-record"
import { apiRequest } from "@/shared/api/api-client"

export interface RuntimeJobFilters {
  userId?: string
  agent?: string
  executionStatus?: string
  deliveryStatus?: string
  failureStage?: string
  model?: string
}

export async function listRuntimeJobs(filters: RuntimeJobFilters = {}) {
  const params = new URLSearchParams({ limit: "50" })
  const values: Array<[keyof RuntimeJobFilters, string]> = [
    ["userId", "user_id"],
    ["agent", "agent"],
    ["executionStatus", "execution_status"],
    ["deliveryStatus", "delivery_status"],
    ["failureStage", "failure_stage"],
    ["model", "model"],
  ]
  for (const [key, queryKey] of values) {
    const value = filters[key]?.trim()
    if (value) params.set(queryKey, value)
  }
  return runtimeJobPageSchema.parse(
    await apiRequest(`/api/admin/jobs?${params.toString()}`)
  ).items
}

export async function getRuntimeJob(jobId: string) {
  return runtimeJobDetailSchema.parse(
    await apiRequest(`/api/agent/jobs/${encodeURIComponent(jobId)}/evidence`)
  )
}

export async function listRuntimeJobModelCalls(
  jobId: string,
  cursor: string,
  limit = 50
) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set("cursor", cursor)
  return modelCallPageSchema.parse(
    await apiRequest(
      `/api/agent/jobs/${encodeURIComponent(jobId)}/model-calls?${params.toString()}`
    )
  )
}

export async function getConversation(sessionId: string) {
  return conversationDetailSchema.parse(
    await apiRequest(
      `/api/admin/conversations/${encodeURIComponent(sessionId)}`
    )
  )
}
