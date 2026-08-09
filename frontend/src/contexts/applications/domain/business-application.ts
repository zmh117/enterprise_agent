import type { LifecycleStatus } from "@/contexts/agents/domain/agent"

export type Environment = "test" | "production"

export type SessionPolicy = {
  conversation_mode: "channel"
  recent_message_limit: number
  retention_days: number
  continuous_conversation_enabled: boolean
  attachments_enabled: boolean
}

export type ExecutionPolicy = {
  max_turns: number
  timeout_seconds: number
  max_tool_calls: number
}

export type ApplicationTrigger = {
  trigger_type: "dingtalk_private" | "dingtalk_group" | "webhook"
  connector_id: string
  routing_key: string
  actor_policy: "CURRENT_SENDER" | "SERVICE_ACCOUNT"
  service_account_user_id: string
  enabled: boolean
  config: {
    conversation_type: string
    require_mention: boolean
    webhook_definition_id: string
  }
}

export type ApplicationDelivery = {
  delivery_type:
    | "reply_original"
    | "dingtalk_private"
    | "dingtalk_group"
    | "webhook_callback"
  connector_id: string
  enabled: boolean
  config: { target_reference: string; reply_mode: string }
}

export type ApplicationDraftInput = {
  agent_publication_id: string
  mcp_tool_publication_ids: string[]
  session_policy: SessionPolicy
  execution_policy: ExecutionPolicy
  triggers: ApplicationTrigger[]
  deliveries: ApplicationDelivery[]
}

export type ApplicationRevision = ApplicationDraftInput & {
  id: string
  revision: number
  status: string
  config_hash?: string
  validation_errors?: Array<{ field: string; message: string }>
  created_at?: string
  created_by?: string
}

export type ApplicationPublication = {
  id: string
  revision: number
  config_hash: string
  snapshot?: Record<string, unknown>
  runtime_ready?: boolean
  readiness_errors?: Array<{ field: string; message: string }>
  created_at?: string
  created_by?: string
}

export type ApplicationDeployment = {
  id?: string
  environment: Environment
  revision: number
  active: boolean
  publication_id?: string | null
  runtime_ready?: boolean
  readiness_errors?: Array<{ field: string; message: string }>
}

export type BusinessApplicationSummary = {
  id: string
  code: string
  name: string
  description: string
  project_code: string
  owner_user_id: string
  status: LifecycleStatus
  revision: number
  active_environments: string[]
  runtime_ready?: boolean
  readiness_errors?: Array<{ field: string; message: string }>
}

export type BusinessApplicationDetail = BusinessApplicationSummary & {
  draft: ApplicationRevision | null
  publications: ApplicationPublication[]
  deployments: ApplicationDeployment[]
  permissions: { edit: boolean; publish: boolean; activate: boolean }
}

export type ApplicationAgentOption = {
  id: string
  code: string
  revision: number
  project_code: string
  status: string
  config_hash: string
}

export type ApplicationToolOption = {
  id: string
  code: string
  name: string
  server_code: string
  server_version: string
  tool_name: string
  required_scope: string
  tool_schema_hash: string
  resource_kind?: string
  resource_code?: string
  resource_deployment_id?: string
  resource_revision_id?: string
  config_hash: string
  status: string
}

export type ApplicationConnectorOption = {
  id: string
  connector_type: string
  name: string
  enabled: boolean
  allow_ingress: boolean
  allow_delivery: boolean
}

export type ApplicationCatalog = {
  agents: ApplicationAgentOption[]
  mcp_tools_by_agent_publication: Record<string, ApplicationToolOption[]>
  connectors: ApplicationConnectorOption[]
  runtime_contract: Record<string, string>
}
