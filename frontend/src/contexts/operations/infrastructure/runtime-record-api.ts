import {
  conversationDetailSchema,
  runtimeJobDetailSchema,
  runtimeJobPageSchema,
} from "@/contexts/operations/domain/runtime-record"
import { apiRequest } from "@/shared/api/api-client"

export async function listRuntimeJobs() {
  return runtimeJobPageSchema.parse(
    await apiRequest("/api/admin/jobs?limit=50"),
  ).items
}

export async function getRuntimeJob(jobId: string) {
  return runtimeJobDetailSchema.parse(
    await apiRequest(`/api/admin/jobs/${encodeURIComponent(jobId)}`),
  )
}

export async function getConversation(sessionId: string) {
  return conversationDetailSchema.parse(
    await apiRequest(
      `/api/admin/conversations/${encodeURIComponent(sessionId)}`,
    ),
  )
}
