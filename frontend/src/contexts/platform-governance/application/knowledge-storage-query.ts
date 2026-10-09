import { useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import type { KnowledgeStorage } from "@/contexts/platform-governance/domain/knowledge-resource"
import { getKnowledgeContentCatalog } from "@/contexts/platform-governance/infrastructure/knowledge-resource-api"

export const knowledgeContentCatalogKey = [
  "platform-governance",
  "knowledge-content",
] as const

export function useKnowledgeContentCatalog(
  storage: KnowledgeStorage | null,
  enabled: boolean
) {
  return useQuery({
    queryKey: [...knowledgeContentCatalogKey, storage],
    queryFn: () => getKnowledgeContentCatalog(storage!),
    enabled: enabled && storage !== null,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })
}

export function useKnowledgeStorage(initial: KnowledgeStorage | null = null) {
  const [storage, updateStorage] = useState<KnowledgeStorage | null>(initial)
  const probe = useMutation({
    mutationFn: async (value: KnowledgeStorage) => ({
      key: JSON.stringify(value),
      catalog: await getKnowledgeContentCatalog(value),
    }),
    retry: false,
  })
  const catalog =
    storage && probe.data?.key === JSON.stringify(storage)
      ? probe.data.catalog
      : undefined
  function setStorage(value: KnowledgeStorage | null) {
    updateStorage(value)
    probe.reset()
  }
  return { storage, setStorage, probe, catalog }
}
