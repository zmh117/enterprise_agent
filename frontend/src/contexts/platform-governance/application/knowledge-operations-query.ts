import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiRequest } from "@/shared/api/api-client"
import { planConfigurationSchema } from "../domain/knowledge-operations"
import {
  operationsSchema,
  operationSchema,
  eventsSchema,
  planSchema,
  type OperationRequest,
} from "../domain/knowledge-operations"

const base = "/api/platform/knowledge/operations"
const key = ["knowledge-operations"]
export function useKnowledgePlanConfiguration(id?: string) {
  return useQuery({
    queryKey: [...key, "configuration", id],
    enabled: Boolean(id),
    queryFn: async () =>
      planConfigurationSchema.parse(
        await apiRequest(
          `${base}/plans/${encodeURIComponent(id!)}/configuration`
        )
      ),
  })
}
export function useKnowledgeOperations(enabled: boolean) {
  return useQuery({
    queryKey: key,
    enabled,
    queryFn: async () => operationsSchema.parse(await apiRequest(base)),
    refetchInterval: 3000,
  })
}
export function useKnowledgeOperationEvents(
  operationId: string | null,
  service: string,
  enabled: boolean
) {
  const params = new URLSearchParams()
  if (operationId) params.set("operation_id", operationId)
  if (service) params.set("service", service)
  return useQuery({
    queryKey: [...key, "events", operationId, service],
    enabled,
    queryFn: async () =>
      eventsSchema.parse(await apiRequest(`${base}/events?${params}`)),
    refetchInterval: 3000,
  })
}
type Command =
  | { action: "submit"; input: OperationRequest }
  | { action: "retry"; id: string }
  | { action: "schedule"; id: string; enabled: boolean; revision: number }
  | { action: "configure"; input: Record<string, unknown> }
export function useKnowledgeOperationsCommand() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (command: Command) => {
      if (command.action === "submit")
        return operationSchema.parse(
          await apiRequest(base, { method: "POST", body: command.input })
        )
      if (command.action === "retry")
        return operationSchema.parse(
          await apiRequest(`${base}/${encodeURIComponent(command.id)}/retry`, {
            method: "POST",
            body: {},
          })
        )
      if (command.action === "configure")
        return planSchema.parse(
          await apiRequest(`${base}/plans`, {
            method: "POST",
            body: command.input,
          })
        )
      return planSchema.parse(
        await apiRequest(
          `${base}/plans/${encodeURIComponent(command.id)}/schedule`,
          {
            method: "POST",
            body: {
              enabled: command.enabled,
              expected_revision: command.revision,
            },
          }
        )
      )
    },
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  })
}
