export type LifecycleStatus = "enabled" | "disabled" | "archived"

export type AgentDefinition = {
  id: string
  code: string
  name: string
  description: string
  project_code: string
  status: LifecycleStatus
  revision: number
  current_publication_id?: string | null
  management_mode?: "editable" | "read_only"
}

export type ValidationError = { field: string; message: string }

export type AgentDraftConfig = {
  business_role: string
  business_instructions: string
  model_policy: {
    runtime: string
    model: string
    model_connection_revision_id: string
  }
  execution: { max_turns: number; timeout_seconds: number }
  skills: string[]
  routing: { project_code: string }
  channels: { ingress: string[]; delivery: string[] }
  mcp_tool_publication_ids: string[]
}

export type AgentRevision = {
  id: string
  revision: number
  status: string
  config_hash: string
  config: AgentDraftConfig
  validation_errors?: ValidationError[]
  created_at?: string
  created_by?: string
}

export type AgentPublication = {
  id: string
  revision: number
  config_hash: string
  snapshot?: Record<string, unknown>
  active_applications?: Array<Record<string, unknown>>
  created_at?: string
  created_by?: string
}

export type AgentSummary = AgentDefinition & {
  current_publication?: Pick<
    AgentPublication,
    "id" | "revision" | "config_hash"
  > | null
  model_connection_status?: string
  active_application_count?: number
  active_applications?: Array<Record<string, unknown>>
}

export type McpToolOption = {
  id: string
  code?: string
  name?: string
  tool_name?: string
  server_code?: string
  server_version?: string
  schema_hash?: string
  resource_kind?: string
  resource_code?: string
  status?: string
}

export type ModelConnectionSummary = {
  id: string
  code: string
  name?: string
  status: string
  revision: number
  current_revision_id?: string | null
  current_revision?: ModelConnectionRevision | null
}

export type ModelConnectionRevision = {
  id: string
  revision: number
  status?: string
  config_hash?: string
  config: Omit<ModelConnectionConfig, "base_url">
  provider_host?: string
  credential?: {
    configured: boolean
    rotation_required: boolean
    version?: number
  }
  last_test?: Record<string, unknown> | null
  created_at?: string
}

export type ModelConnectionConfig = {
  schema_version: 1
  protocol: "anthropic_compatible"
  base_url: string
  model: string
  default_opus_model: string
  default_sonnet_model: string
  default_haiku_model: string
  subagent_model: string
  effort_level: "low" | "medium" | "high" | "max"
}

export type ModelConnectionDetail = ModelConnectionSummary & {
  revisions: ModelConnectionRevision[]
  permissions: {
    can_edit: boolean
    can_manage_credential: boolean
    can_test: boolean
  }
}

export type AgentDetail = {
  definition: AgentDefinition
  draft: AgentRevision | null
  current_publication: AgentPublication | null
  catalog: {
    models: string[]
    skills: string[]
    connectors: Array<Record<string, unknown>>
    mcp_tools: McpToolOption[]
  }
  model_connections: ModelConnectionSummary[]
  management_mode: "editable" | "read_only"
  permissions: {
    can_edit: boolean
    can_publish: boolean
    can_manage_credential: boolean
  }
}

export type AgentListResponse = {
  agents: AgentSummary[]
  permissions: { can_create: boolean }
}
