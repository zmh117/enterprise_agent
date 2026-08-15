import {
  conversationDetailSchema,
  fileOperationsSchema,
  modelCallPageSchema,
  runtimeJobDetailSchema,
  runtimeJobPageSchema,
} from "@/contexts/operations/domain/runtime-record"
import { apiRequest } from "@/shared/api/api-client"

export interface RuntimeJobFilters {
  start?: string
  end?: string
  username?: string
  applicationName?: string
}

export async function listRuntimeJobs(filters: RuntimeJobFilters = {}) {
  const params = new URLSearchParams({ limit: "50" })
  const values: Array<[keyof RuntimeJobFilters, string]> = [
    ["username", "username"],
    ["applicationName", "application_name"],
  ]
  for (const [key, queryKey] of values) {
    const value = filters[key]?.trim()
    if (value) params.set(queryKey, value)
  }
  for (const key of ["start", "end"] as const) {
    const value = filters[key]?.trim()
    if (value) params.set(key, apiTimestamp(value))
  }
  return runtimeJobPageSchema.parse(
    await apiRequest(`/api/admin/jobs?${params.toString()}`)
  ).items
}

function apiTimestamp(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString()
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

export async function getFileOperations() {
  return fileOperationsSchema.parse(await apiRequest("/api/admin/file-operations"))
}
