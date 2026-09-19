import { z } from "zod"

const identifier = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/)
const revision = z.number().int().nonnegative()
const hash = z.string().regex(/^[0-9a-f]{64}$/)
export const knowledgeBindingSchema = z.object({
  id: identifier,
  source_id: identifier,
  revision,
  instance_code: identifier,
  team_id: identifier,
  state: z.enum(["PENDING", "CONFIRMED", "VERIFIED", "REVOKED"]),
})
export const knowledgeSourcesSchema = z.object({
  sources: z.array(
    z.object({
      id: identifier,
      code: z.string(),
      display_name: z.string(),
      source_system: z.string(),
      origin_state: z.string(),
    })
  ),
  bindings: z.array(knowledgeBindingSchema),
})
export const knowledgeCatalogSchema = z.object({
  bases: z.array(
    z.object({
      id: identifier,
      code: z.string(),
      display_name: z.string(),
      state: z.string(),
      source_ids: z.array(identifier),
    })
  ),
  indexes: z.array(
    z.object({
      id: identifier,
      code: z.string(),
      knowledge_base_id: identifier,
      state: z.string(),
      profile_hash: hash,
      corpus_hash: hash,
    })
  ),
})
const resourceRevision = z.object({
  id: identifier,
  revision,
  binding_id: identifier,
  index_id: identifier,
  config_hash: hash,
})
export const knowledgeResourceSchema = z.object({
  id: identifier,
  knowledge_base_id: identifier,
  code: z.string(),
  name: z.string(),
  revision,
  status: z.enum(["enabled", "disabled", "archived"]),
  draft: resourceRevision.nullable(),
  published: resourceRevision.nullable(),
  verification: z
    .object({ status: z.enum(["VERIFIED", "FAILED"]), config_hash: hash })
    .nullable(),
})
export const knowledgeResourcesSchema = z.object({
  resources: z.array(knowledgeResourceSchema),
})
export type KnowledgeResource = z.infer<typeof knowledgeResourceSchema>
export type KnowledgeBinding = z.infer<typeof knowledgeBindingSchema>
export type KnowledgeInventory = z.infer<typeof knowledgeSourcesSchema> &
  z.infer<typeof knowledgeCatalogSchema> &
  z.infer<typeof knowledgeResourcesSchema>

export const newKnowledgeResourceSchema = z
  .object({
    knowledge_base_id: identifier,
    code: identifier,
    name: z.string().trim().min(1).max(120),
  })
  .strict()
export type KnowledgeCommand =
  | { kind: "create"; input: z.infer<typeof newKnowledgeResourceSchema> }
  | {
      kind: "draft"
      id: string
      input: { expected_revision: number; binding_id: string; index_id: string }
    }
  | {
      kind: "verify" | "publish"
      id: string
      input: { expected_revision: number }
    }
  | {
      kind: "status"
      id: string
      input: { expected_revision: number; status: KnowledgeResource["status"] }
    }

export function canPublishKnowledge(resource: KnowledgeResource) {
  return (
    resource.status === "enabled" &&
    resource.draft !== null &&
    resource.verification?.status === "VERIFIED" &&
    resource.verification.config_hash === resource.draft.config_hash
  )
}

export function knowledgeStatus(value: string) {
  return (
    (
      {
        storage_only: "仅存储",
        offline_unverified: "离线导入",
        READY: "已就绪",
        BUILDING: "构建中",
        FAILED: "失败",
        PENDING: "待核验",
        CONFIRMED: "来源已确认",
        VERIFIED: "已核验",
        REVOKED: "已撤销",
        enabled: "启用",
        disabled: "停用",
        archived: "已归档",
      } as Record<string, string>
    )[value] ?? "未就绪"
  )
}
