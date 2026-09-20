import {
  knowledgeCatalogSchema,
  knowledgeResourcesSchema,
  knowledgeResourceSchema,
  knowledgeSourcesSchema,
  newKnowledgeResourceSchema,
  type KnowledgeCommand,
  type KnowledgeInventory,
  type KnowledgeStorage,
} from "@/contexts/platform-governance/domain/knowledge-resource"
import { apiRequest } from "@/shared/api/api-client"

const base = "/api/platform/knowledge"

export async function getKnowledgeContentCatalog(storage: KnowledgeStorage) {
  return knowledgeCatalogSchema.parse(
    await apiRequest(`${base}/content-catalog`, {
      method: "POST",
      body: { storage },
    })
  )
}

export async function getKnowledgeInventory(): Promise<KnowledgeInventory> {
  const [sources, catalog, resources] = await Promise.all([
    apiRequest(`${base}/sources`),
    apiRequest(`${base}/catalog`),
    apiRequest(`${base}/resources`),
  ])
  return {
    ...knowledgeSourcesSchema.parse(sources),
    ...knowledgeCatalogSchema.parse(catalog),
    ...knowledgeResourcesSchema.parse(resources),
  }
}

export async function changeKnowledgeResource(command: KnowledgeCommand) {
  if (command.kind === "create") {
    return knowledgeResourceSchema.parse(
      await apiRequest(`${base}/resources`, {
        method: "POST",
        body: newKnowledgeResourceSchema.parse(command.input),
      })
    )
  }
  const id = encodeURIComponent(command.id)
  return knowledgeResourceSchema.parse(
    await apiRequest(`${base}/resources/${id}/${command.kind}`, {
      method: command.kind === "draft" ? "PUT" : "POST",
      body: command.input,
    })
  )
}
