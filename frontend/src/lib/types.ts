export type Status = "enabled" | "disabled";

export type Principal = {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
  auth_source: string;
  capabilities: {
    users_manage: boolean;
    roles_manage: boolean;
    identities_manage: boolean;
    agent_edit: boolean;
    agent_publish: boolean;
    audit_read: boolean;
    webhook_read: boolean;
    webhook_edit: boolean;
    webhook_publish: boolean;
    webhook_rotate: boolean;
    webhook_manage_service_account: boolean;
  };
};

export type User = {
  id: string;
  username: string;
  display_name: string;
  email: string;
  status: Status;
  revision: number;
};

export type Role = {
  id: string;
  code: string;
  name: string;
  description: string;
  status: Status;
  revision: number;
  membership_id?: string;
  membership_revision?: number;
};

export type Identity = {
  id: string;
  user_id: string;
  provider: string;
  tenant_code: string;
  external_subject_id: string;
  connector_id: string;
  display_name: string;
  status: Status;
  revision: number;
  last_seen_at?: string;
};

export type Session = {
  id: string;
  status: string;
  created_at: string;
  last_seen_at: string;
  idle_expires_at: string;
  absolute_expires_at: string;
  user_agent_summary: string;
  remote_address_summary: string;
};

export type Permission = {
  id: string;
  subject_type: "user" | "role";
  subject_code: string;
  resource_type: string;
  resource_code: string;
  action: string;
  effect: "allow" | "deny";
  priority: number;
  status: Status;
  revision: number;
};

export type Connector = {
  id: string;
  connector_id?: string;
  name: string;
  connector_type?: string;
  tenant_code?: string;
  allow_ingress?: number;
  allow_delivery?: number;
};

export type AgentConfig = {
  business_role: string;
  business_instructions: string;
  model_policy: { model: string };
  execution: { max_turns: number; timeout_seconds: number };
  tools: string[];
  skills: string[];
  routing: { project_code: string };
  channels: { ingress: string[]; delivery: string[] };
};

export type AgentRevision = {
  id: string;
  revision: number;
  status: string;
  config_hash: string;
  config: AgentConfig;
  validation: { valid?: boolean; errors?: Array<{ field: string; message: string }> };
};

export type Publication = {
  id: string;
  revision: number;
  schema_version: number;
  config_hash: string;
  snapshot: AgentConfig;
  published_by: string;
  published_at: string;
};

export type AgentPayload = {
  definition: { code: string; name: string; description: string; status: Status };
  draft: AgentRevision | null;
  current_publication: Publication | null;
  catalog: { models: string[]; tools: string[]; skills: string[]; connectors: Connector[] };
};

export type AuditEvent = {
  id: string;
  event_type: string;
  actor_id?: string;
  status: string;
  summary: string;
  created_at: string;
  payload_summary: { payload?: string; truncated?: boolean };
};

export type WebhookRoutingRule = {
  mode: "fixed" | "extract";
  value: string;
  pointer: string;
  allowed_values: string[];
};

export type WebhookTriggerConfig = {
  schema_version: 1;
  adapter: "grafana_alertmanager_v1" | "generic_json_v1";
  authentication: {
    type: "bearer_v1" | "hmac_sha256_v1";
    secret_ref: string;
    timestamp_header: string;
    nonce_header: string;
    signature_header: string;
    window_seconds: number;
  };
  mapping: {
    variables: Record<string, string>;
    filters: Array<{ pointer: string; operator: "exists" | "equals" | "in" | "not_equals"; value?: unknown }>;
    message_template: string;
    event_id_pointer: string;
    status_pointer: string;
  };
  routing: Record<"project_code" | "environment" | "base" | "workshop" | "service", WebhookRoutingRule>;
  agent: { code: string; publication_id: string };
  delivery: { type: string; connector_id: string; target: Record<string, string>; options: Record<string, unknown> };
  idempotency: { cooldown_seconds: number };
  limits: { requests_per_minute: number; max_in_flight: number; max_alerts: number };
};

export type WebhookTriggerDefinition = {
  id: string;
  code: string;
  name: string;
  trigger_type: "grafana" | "generic";
  public_id: string;
  connector_id: string;
  service_account_id: string;
  service_account_username: string;
  service_account_display_name: string;
  service_account_status: Status;
  status: Status;
  current_publication_id?: string;
  revision: number;
  publication_revision?: number;
  agent_publication_id?: string;
  recent_event_status?: string;
  recent_event_at?: string;
  event_count?: number;
  rejected_event_count?: number;
  failed_event_count?: number;
  created_at: string;
  updated_at: string;
};

export type WebhookRevision = {
  id: string;
  revision: number;
  status: string;
  config_hash: string;
  config: WebhookTriggerConfig;
  validation: {
    valid?: boolean;
    errors?: Array<{ field: string; message: string }>;
    effective_read_only_tools?: string[];
    agent_publication_id?: string;
    agent_revision?: number;
  };
};

export type WebhookPublication = {
  id: string;
  revision: number;
  config_hash: string;
  agent_publication_id: string;
  agent_revision: number;
  snapshot: WebhookTriggerConfig & { service_account_id: string; source_connector_id: string };
  published_by: string;
  published_at: string;
};

export type WebhookTriggerPayload = {
  definition: WebhookTriggerDefinition;
  draft: WebhookRevision | null;
  current_publication: WebhookPublication | null;
  publications: WebhookPublication[];
};

export type WebhookEvent = {
  id: string;
  trigger_code: string;
  trigger_name: string;
  trigger_revision: number;
  status: string;
  auth_result: string;
  filter_result: string;
  error_code: string;
  error_summary: string;
  external_event_id: string;
  correlation_id: string;
  job_id?: string;
  request_bytes: number;
  safe_summary: Record<string, unknown>;
  normalized_event: Record<string, unknown>;
  received_at: string;
};
