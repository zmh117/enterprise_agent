import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  changeKnowledgeResource,
  getKnowledgeInventory,
} from "@/contexts/platform-governance/infrastructure/knowledge-resource-api"
import { knowledgeContentCatalogKey } from "./knowledge-storage-query"

const key = ["platform-governance", "knowledge"] as const
export function useKnowledgeInventory(enabled: boolean) {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: key,
    queryFn: getKnowledgeInventory,
    enabled,
    retry: false,
  })
  return {
    ...query,
    refresh: () =>
      Promise.all([
        query.refetch(),
        client.invalidateQueries({ queryKey: knowledgeContentCatalogKey }),
      ]),
  }
}
export function useKnowledgeCommand() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: changeKnowledgeResource,
    retry: false,
    onSuccess: async (resource, command) => {
      const refresh = client.invalidateQueries({ queryKey: key })
      if (
        command.kind === "status" &&
        command.input.status === "archived" &&
        resource &&
        "kind" in resource &&
        resource.kind === "code"
      ) {
        await Promise.all([
          refresh,
          client.invalidateQueries({ queryKey: ["code-checkouts"] }),
        ])
      } else {
        await refresh
      }
    },
  })
}
