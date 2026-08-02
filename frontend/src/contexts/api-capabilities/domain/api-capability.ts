import { z } from "zod"

const jsonObjectSchema = z.record(z.string(), z.unknown())

export const authenticationProfileSchema = z.object({
  schema_version: z.literal(1),
  login: z.object({
    method: z.literal("POST"),
    relative_path: z.string(),
    email_field: z.string(),
    password_field: z.string(),
  }),
  extract: z.object({
    token_path: z.string(),
    user_id_path: z.string(),
    display_name_path: z.string(),
    teams_path: z.string(),
    team_id_field: z.string(),
    team_name_field: z.string(),
  }),
  inject: z.object({
    header_name: z.string(),
    value_prefix: z.string(),
  }),
})

export const connectionRevisionSchema = z
  .object({
    id: z.string(),
    connection_id: z.string(),
    revision: z.number(),
    status: z.enum(["PUBLISHED", "DISABLED", "ARCHIVED"]),
    origin_scheme: z.string(),
    origin_host: z.string(),
    origin_port: z.number(),
    allow_plain_http: z.union([z.boolean(), z.number()]).transform(Boolean),
    connect_timeout_ms: z.number(),
    read_timeout_ms: z.number(),
    max_response_bytes: z.number(),
    authentication_profile_revision_id: z.string(),
    authentication: authenticationProfileSchema,
    content_hash: z.string(),
    published_at: z.string(),
  })
  .passthrough()

export const connectionDraftSchema = z
  .object({
    id: z.string(),
    draft_revision: z.number(),
    status: z.enum(["DRAFT", "VERIFIED"]),
    origin_scheme: z.string(),
    origin_host: z.string(),
    origin_port: z.number(),
    allow_plain_http: z.union([z.boolean(), z.number()]).transform(Boolean),
    connect_timeout_ms: z.number(),
    read_timeout_ms: z.number(),
    max_response_bytes: z.number(),
    content_hash: z.string(),
    authentication_profile: z.object({
      id: z.string(),
      draft_revision: z.number(),
      status: z.enum(["DRAFT", "VERIFIED"]),
      config: authenticationProfileSchema,
      content_hash: z.string(),
    }).passthrough(),
  })
  .passthrough()

export const apiConnectionSchema = z
  .object({
    id: z.string(),
    code: z.string(),
    name: z.string(),
    provider: z.literal("ones"),
    status: z.string(),
    revision: z.number(),
    draft: connectionDraftSchema.nullable(),
    published_revisions: z.array(connectionRevisionSchema),
  })
  .passthrough()

const capabilityDefinitionSchema = z.object({
  name: z.string(),
  description: z.string(),
  operation_semantics: z.literal("QUERY"),
  data_classification: z.literal("INTERNAL"),
  input_schema: jsonObjectSchema,
  output_schema: jsonObjectSchema,
})

const handlerSchema = z.object({
  method: z.enum(["GET", "POST"]),
  relative_path: z.string(),
  graphql_document: z.string(),
})

export const capabilityDraftSchema = z
  .object({
    id: z.string(),
    draft_revision: z.number(),
    status: z.enum(["DRAFT", "VERIFIED"]),
    connection_revision_id: z.string(),
    authentication_profile_revision_id: z.string(),
    capability: capabilityDefinitionSchema,
    handler: handlerSchema,
    mapping_ast: jsonObjectSchema,
    content_hash: z.string(),
  })
  .passthrough()

export const capabilityReleaseSchema = z
  .object({
    id: z.string(),
    capability_id: z.string(),
    identifier: z.string(),
    release_revision: z.number(),
    status: z.enum(["ACTIVE", "DEPRECATED", "DISABLED", "ARCHIVED"]),
    name: z.string(),
    description: z.string(),
    operation_semantics: z.literal("QUERY"),
    data_classification: z.literal("INTERNAL"),
    release_note: z.string(),
    deprecation_reason: z.string(),
    replacement_release_id: z.string().nullable().optional(),
    config_hash: z.string(),
    published_at: z.string(),
  })
  .passthrough()

export const apiCapabilitySchema = z
  .object({
    id: z.string(),
    identifier: z.string(),
    name: z.string(),
    status: z.string(),
    revision: z.number(),
    draft: capabilityDraftSchema.nullable(),
    releases: z.array(capabilityReleaseSchema),
  })
  .passthrough()

export const capabilityPreviewSchema = z.object({
  method: z.enum(["GET", "POST"]),
  relative_path: z.string(),
  query: jsonObjectSchema,
  body: jsonObjectSchema,
  normalized_output: z.unknown(),
})

export type AuthenticationProfile = z.infer<typeof authenticationProfileSchema>
export type ApiConnection = z.infer<typeof apiConnectionSchema>
export type ApiConnectionRevision = z.infer<typeof connectionRevisionSchema>
export type ApiCapability = z.infer<typeof apiCapabilitySchema>
export type CapabilityRelease = z.infer<typeof capabilityReleaseSchema>
export type CapabilityPreview = z.infer<typeof capabilityPreviewSchema>

export type ConnectionDraftInput = {
  origin: {
    scheme: "https" | "http"
    host: string
    port: number
    allow_plain_http: boolean
    connect_timeout_ms: number
    read_timeout_ms: number
    max_response_bytes: number
  }
  authentication: AuthenticationProfile
}

export type CapabilityDraftInput = {
  connection_revision_id: string
  authentication_profile_revision_id: string
  capability: z.infer<typeof capabilityDefinitionSchema>
  handler: z.infer<typeof handlerSchema>
  mapping_ast: Record<string, unknown>
}

export const defaultOnesAuthenticationProfile: AuthenticationProfile = {
  schema_version: 1,
  login: {
    method: "POST",
    relative_path: "/project/api/project/auth/login",
    email_field: "email",
    password_field: "password",
  },
  extract: {
    token_path: "$.user.token",
    user_id_path: "$.user.uuid",
    display_name_path: "$.user.name",
    teams_path: "$.teams",
    team_id_field: "uuid",
    team_name_field: "name",
  },
  inject: {
    header_name: "Ones-Auth-Token",
    value_prefix: "",
  },
}

export function parseJsonObject(value: string, label: string) {
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    throw new Error(`${label} 不是合法 JSON`)
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
  return parsed as Record<string, unknown>
}

const forbiddenPreviewKey = /password|token|cookie|authorization|auth_header|raw_response/i

export function assertSafePreview(value: unknown, path = "preview"): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertSafePreview(item, `${path}.${index}`))
    return
  }
  if (!value || typeof value !== "object") return
  for (const [key, item] of Object.entries(value)) {
    if (forbiddenPreviewKey.test(key)) {
      throw new Error(`服务端预览包含禁止字段：${path}.${key}`)
    }
    assertSafePreview(item, `${path}.${key}`)
  }
}
