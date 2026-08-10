import { apiRequest, createIdempotencyKey } from "@/shared/api/api-client"

export type McpServerSummary = {
  server_code: string
  source: string
  transport: { type: string; authentication: string }
  health: {
    status?: string
    server_version?: string
    generation_status?: string
    active_generation_count?: number
    safe_error_code?: string
  }
  active_publications: number
}

export type McpCatalogEntry = {
  catalog_key: string
  server_code: string
  server_version: string
  tool_name: string
  required_scope: string
  resource_kind: string | null
  tool_schema_hash: string
}

export type McpTool = {
  id: string
  code: string
  name: string
  lifecycle_status: string
  revision: number
  catalog_key: string
  draft: null | {
    id: string
    status: string
    catalog_key: string
    resource_deployment_id: string
  }
  publications: Array<{
    id: string
    revision: number
    status: string
    server_code: string
    tool_name: string
    resource_deployment_id: string
    published_at?: string
  }>
}

export type McpResourceStatus = {
  resource: {
    id: string
    code: string
    name: string
    kind: string
    lifecycle_status: string
    revision: number
  }
  draft?: null | { status?: string; revision?: number }
  verification?: null | { status?: string; safe_error_code?: string }
  deployment?: null | {
    id?: string
    status?: string
    generation_status?: string
    safe_error_code?: string
    resource_revision?: number
  }
}

export type CredentialSummary = {
  id: string
  code: string
  provider: string
  purpose: string
  status: string
  active_version: number
  configured: boolean
  masked_summary: string
  revision: number
  updated_at?: string | null
}

export type ResourceKind = "DATABASE" | "REDIS" | "LOKI"

type ResourceFormCommon = {
  kind: ResourceKind
  code: string
  name: string
  expected_revision: number
}

export type DatabaseResourceForm = ResourceFormCommon & {
  kind: "DATABASE"
  provider: "mysql" | "postgresql" | "sqlserver" | "oracle"
  host: string
  port: number
  database_name: string
  schema_name: string
  username: string
  credential_id: string
  allowed_tables: string[]
  max_rows: number
  timeout_seconds: number
  tls: boolean
}

export type RedisResourceForm = ResourceFormCommon & {
  kind: "REDIS"
  host: string
  port: number
  redis_database: number
  username: string
  credential_id: string
  key_prefixes: string[]
  scan_limit: number
  timeout_seconds: number
  tls: boolean
}

export type LokiResourceForm = ResourceFormCommon & {
  kind: "LOKI"
  base_url: string
  tenant_id: string
  credential_id: string
  label_scope: Record<string, string>
  max_minutes: number
  max_lines: number
  timeout_seconds: number
}

export type ResourceForm =
  | DatabaseResourceForm
  | RedisResourceForm
  | LokiResourceForm

export async function listMcpServers() {
  const result = await apiRequest<{ servers: McpServerSummary[] }>(
    "/api/admin/mcp/status"
  )
  return result.servers
}

export async function listMcpTools() {
  return apiRequest<{
    tools: McpTool[]
    permissions: { can_create: boolean }
  }>("/api/admin/mcp/tool-publications")
}

export async function listMcpCatalog() {
  const result = await apiRequest<{ catalog: McpCatalogEntry[] }>(
    "/api/admin/mcp/tools"
  )
  return result.catalog
}

export async function createMcpTool(input: {
  code: string
  name: string
  catalog_key: string
  resource_deployment_id: string
}) {
  return apiRequest<{ tool: McpTool }>("/api/admin/mcp/tool-publications", {
    method: "POST",
    headers: {
      "Idempotency-Key": createIdempotencyKey("mcp-tool-create"),
    },
    body: { expected_revision: 0, ...input },
  })
}

export async function transitionMcpTool(
  code: string,
  action: "verify" | "publish" | "disable",
  expectedRevision: number
) {
  return apiRequest<Record<string, unknown>>(
    `/api/admin/mcp/tool-publications/${encodeURIComponent(code)}/${action}`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey(`mcp-tool-${action}`),
      },
      body: { expected_revision: expectedRevision },
    }
  )
}

export async function listMcpResources() {
  const result = await apiRequest<{ resources: McpResourceStatus[] }>(
    "/api/admin/mcp/resources"
  )
  return result.resources
}

export async function listResourceCredentialCandidates() {
  const result = await apiRequest<{ items: CredentialSummary[] }>(
    "/api/admin/mcp/resource-credential-candidates"
  )
  return result.items
}

export async function getResourceForm(code: string) {
  const result = await apiRequest<{ form: ResourceForm }>(
    `/api/admin/mcp/resource-forms/${encodeURIComponent(code)}`
  )
  return result.form
}

export async function saveResourceForm(form: ResourceForm) {
  return apiRequest<{ resource: Record<string, unknown> }>(
    "/api/admin/mcp/resource-drafts",
    {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey("mcp-resource-draft"),
      },
      body: form,
    }
  )
}

export async function transitionMcpResource(
  code: string,
  action: "verify" | "publish" | "unpublish",
  expectedRevision: number
) {
  return apiRequest<Record<string, unknown>>(
    `/api/admin/mcp/resources/${encodeURIComponent(code)}/${action}`,
    {
      method: "POST",
      body: {
        expected_revision: expectedRevision,
        ...(action === "publish"
          ? { idempotency_key: createIdempotencyKey("mcp-resource-publish") }
          : {}),
      },
    }
  )
}

export async function listCredentials() {
  const result = await apiRequest<{ secrets: CredentialSummary[] }>(
    "/api/platform/secrets"
  )
  return result.secrets
}

export async function createCredential(input: {
  code: string
  purpose: string
  value: string
}) {
  return apiRequest<{ secret: CredentialSummary }>("/api/platform/secrets", {
    method: "POST",
    headers: {
      "Idempotency-Key": createIdempotencyKey("credential-create"),
    },
    body: input,
  })
}

export async function rotateCredential(
  code: string,
  expectedRevision: number,
  value: string
) {
  return apiRequest<{ secret: CredentialSummary }>(
    `/api/platform/secrets/${encodeURIComponent(code)}/rotate`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey("credential-rotate"),
      },
      body: { expected_revision: expectedRevision, value },
    }
  )
}

export async function disableCredential(
  code: string,
  expectedRevision: number
) {
  return apiRequest<{ secret: CredentialSummary }>(
    `/api/platform/secrets/${encodeURIComponent(code)}/disable`,
    {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey("credential-disable"),
      },
      body: { expected_revision: expectedRevision },
    }
  )
}
