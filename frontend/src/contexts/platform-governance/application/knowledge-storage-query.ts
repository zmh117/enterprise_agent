import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import type { KnowledgeStorage } from "@/contexts/platform-governance/domain/knowledge-resource"
import { getKnowledgeContentCatalog } from "@/contexts/platform-governance/infrastructure/knowledge-resource-api"

export function useKnowledgeStorage(initial: KnowledgeStorage | null = null) {
  const [storage, setStorage] = useState<KnowledgeStorage | null>(initial)
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
  return { storage, setStorage, probe, catalog }
}
