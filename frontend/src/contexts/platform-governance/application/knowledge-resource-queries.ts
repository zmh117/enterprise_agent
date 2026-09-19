import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  changeKnowledgeResource,
  getKnowledgeInventory,
} from "@/contexts/platform-governance/infrastructure/knowledge-resource-api"

const key = ["platform-governance", "knowledge"] as const
export function useKnowledgeInventory(enabled: boolean) {
  return useQuery({
    queryKey: key,
    queryFn: getKnowledgeInventory,
    enabled,
    retry: false,
  })
}
export function useKnowledgeCommand() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: changeKnowledgeResource,
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  })
}
