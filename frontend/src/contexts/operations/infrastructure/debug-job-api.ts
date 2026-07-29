import {
  debugJobCreateResponseSchema,
  debugOptionsSchema,
} from "@/contexts/operations/domain/debug-job"
import { apiRequest } from "@/shared/api/api-client"

export async function getDebugJobOptions() {
  return debugOptionsSchema.parse(
    await apiRequest("/api/agent/jobs/_debug-options")
  )
}

export async function createDebugJob(input: {
  message: string
  application_id: string
  execution_scope_id: string
  delivery_binding_id: string
  idempotency_key: string
}) {
  return debugJobCreateResponseSchema.parse(
    await apiRequest("/api/agent/jobs", {
      method: "POST",
      body: input,
    })
  )
}
