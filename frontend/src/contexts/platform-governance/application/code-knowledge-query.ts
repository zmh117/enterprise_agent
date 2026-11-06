import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiRequest } from "@/shared/api/api-client"
import {
  codeKnowledgeSchema,
  codeDetailSchema,
  type CodeCommand,
} from "../domain/code-knowledge"

const base = "/api/platform/knowledge/code"
const key = ["code-knowledge"]
export function useCodeKnowledge(enabled: boolean) {
  return useQuery({
    queryKey: key,
    enabled,
    refetchInterval: 5000,
    queryFn: async () => codeKnowledgeSchema.parse(await apiRequest(base)),
  })
}
export function useCodeKnowledgeDetail(id?: string, after = "") {
  return useQuery({
    queryKey: [...key, "build", id, after],
    enabled: Boolean(id),
    queryFn: async () =>
      codeDetailSchema.parse(
        await apiRequest(
          `${base}/builds/${encodeURIComponent(id!)}?after=${encodeURIComponent(after)}`
        )
      ),
  })
}
export function useCodeKnowledgeCommand() {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: (command: CodeCommand) => {
      const path =
        command.action === "start"
          ? "/builds"
          : command.action === "plan" ||
              command.action === "version" ||
              command.action === "site" ||
              command.action === "retry_source"
            ? `/sources/${encodeURIComponent(command.id)}/${{ plan: "plan", version: "versions", site: "sites", retry_source: "retry" }[command.action]}`
            : command.action === "rollback"
              ? `/sources/${encodeURIComponent(command.id)}/rollback`
              : `/builds/${encodeURIComponent(command.id)}/${command.action}`
      return apiRequest(base + path, {
        method: "POST",
        body:
          command.action === "retry" || command.action === "retry_source"
            ? {}
            : command.input,
      })
    },
    onSuccess: () => cache.invalidateQueries({ queryKey: key }),
  })
}
