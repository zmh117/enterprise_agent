import {
  knowledgeBindingSchema,
  knowledgeCatalogSchema,
  knowledgeResourcesSchema,
  knowledgeResourceSchema,
  knowledgeSourcesSchema,
  newKnowledgeBindingSchema,
  newKnowledgeResourceSchema,
  type KnowledgeCommand,
  type KnowledgeInventory,
} from "@/contexts/platform-governance/domain/knowledge-resource"
import { apiRequest } from "@/shared/api/api-client"

const base = "/api/platform/knowledge"

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
  if (command.kind === "source-create") {
    return knowledgeBindingSchema.parse(
      await apiRequest(`${base}/source-bindings`, {
        method: "POST",
        body: newKnowledgeBindingSchema.parse(command.input),
      })
    )
  }
  const id = encodeURIComponent(command.id)
  if (command.kind === "source-verify" || command.kind === "source-revoke") {
    const result = await apiRequest(
      `${base}/source-bindings/${id}/${command.kind === "source-verify" ? "verify" : "revoke"}`,
      {
        method: "POST",
        body: command.input,
      }
    )
    return command.kind === "source-verify"
      ? knowledgeBindingSchema.parse(result)
      : null
  }
  return knowledgeResourceSchema.parse(
    await apiRequest(`${base}/resources/${id}/${command.kind}`, {
      method: command.kind === "draft" ? "PUT" : "POST",
      body: command.input,
    })
  )
}
