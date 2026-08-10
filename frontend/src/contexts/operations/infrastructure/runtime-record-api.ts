import {
  conversationDetailSchema,
  runtimeJobDetailSchema,
  runtimeJobPageSchema,
  runtimeJobSchema,
} from "@/contexts/operations/domain/runtime-record"
import { z } from "zod"

import { apiRequest, createIdempotencyKey } from "@/shared/api/api-client"

export async function listRuntimeJobs() {
  return runtimeJobPageSchema.parse(
    await apiRequest("/api/me/jobs?limit=50")
  ).items
}

export async function getRuntimeJob(jobId: string) {
  return runtimeJobDetailSchema.parse(
    await apiRequest(`/api/me/jobs/${encodeURIComponent(jobId)}/evidence`)
  )
}

export async function getConversation(sessionId: string) {
  return conversationDetailSchema.parse(
    await apiRequest(
      `/api/me/conversations/${encodeURIComponent(sessionId)}`
    )
  )
}

export async function listAdminRuntimeJobs() {
  return runtimeJobPageSchema.parse(
    await apiRequest("/api/admin/jobs?limit=50")
  ).items
}

export async function getAdminRuntimeJob(jobId: string) {
  return runtimeJobDetailSchema.parse(
    await apiRequest(`/api/admin/jobs/${encodeURIComponent(jobId)}/evidence`)
  )
}

const debugApplicationSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  environment: z.enum(["test", "production"]),
})

export type DebugApplication = z.infer<typeof debugApplicationSchema>

export async function listDebugApplications() {
  const response = z.object({ items: z.array(debugApplicationSchema) }).parse(
    await apiRequest("/api/admin/debug/applications")
  )
  return response.items
}

export async function createDebugJob(input: {
  applicationCode: string
  environment: "test" | "production"
  message: string
}) {
  const response = z.object({ job: runtimeJobSchema }).parse(
    await apiRequest("/api/admin/debug/jobs", {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("debug-job") },
      body: {
        application_code: input.applicationCode,
        environment: input.environment,
        message: input.message,
      },
    })
  )
  return response.job
}

export async function cancelAdminJob(job: {
  id: string
  status: "WAITING_INPUT" | "PENDING" | "RUNNING" | "RETRY_WAIT"
}) {
  return z.object({ job: runtimeJobSchema, cancelled: z.boolean() }).parse(
    await apiRequest(`/api/admin/jobs/${encodeURIComponent(job.id)}/cancel`, {
      method: "POST",
      headers: { "Idempotency-Key": createIdempotencyKey("cancel-job") },
      body: { expected_status: job.status },
    })
  )
}
